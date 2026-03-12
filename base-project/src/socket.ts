import { Server, Socket } from 'socket.io';
import { createAdapter } from '@socket.io/redis-adapter';
import { createClient } from 'redis';
import { Server as HttpServer } from 'http';

// Redis clients for Socket.IO adapter (Pub/Sub for horizontal scaling)
const pubClient = createClient({ url: process.env.REDIS_URL || 'redis://localhost:6379' });
const subClient = pubClient.duplicate();

// Redis client for application state (Rate limiting, Presence)
const redisClient = createClient({ url: process.env.REDIS_URL || 'redis://localhost:6379' });

export async function initializeSocket(httpServer: HttpServer) {
  // Initialize Redis connections
  await Promise.all([pubClient.connect(), subClient.connect(), redisClient.connect()]);

  const io = new Server(httpServer, {
    cors: {
      origin: process.env.FRONTEND_URL || 'http://localhost:3000',
      methods: ['GET', 'POST'],
      credentials: true,
    },
    // Mount Redis adapter for cross-node fan-out
    adapter: createAdapter(pubClient, subClient),
  });

  // Authentication Middleware
  io.use(async (socket, next) => {
    const token = socket.handshake.auth.token;
    if (!token) return next(new Error('Authentication error'));
    
    // TODO: Verify JWT and extract user ID. Mocking for now.
    socket.data.userId = 'user_' + Math.random().toString(36).substr(2, 9);
    next();
  });

  io.on('connection', async (socket: Socket) => {
    const userId = socket.data.userId;
    
    // --- 1. Presence Tracking ---
    // Mark user as online in Redis Hash
    await redisClient.hSet('presence', userId, 'online');
    socket.broadcast.emit('user:presence', { userId, status: 'online' });

    socket.on('disconnect', async () => {
      // Note: In production, track connection counts per user to handle multiple tabs.
      await redisClient.hDel('presence', userId);
      socket.broadcast.emit('user:presence', { userId, status: 'offline' });
    });

    // --- 2. Rate Limiting Logic ---
    const checkRateLimit = async (limit: number, windowSec: number): Promise<boolean> => {
      const key = `rate_limit:messages:${userId}`;
      const currentCount = await redisClient.incr(key);
      
      if (currentCount === 1) {
        await redisClient.expire(key, windowSec);
      }
      return currentCount <= limit;
    };

    // --- 3. Message Send/Receive ---
    socket.on('message:send', async (data, callback) => {
      // Rate limit: 10 messages per 1 second
      const isAllowed = await checkRateLimit(10, 1);
      if (!isAllowed) {
        return callback({ error: 'Rate limit exceeded. Try again in a moment.' });
      }

      const message = {
        id: crypto.randomUUID(),
        senderId: userId,
        channelId: data.channelId,
        content: data.content,
        timestamp: new Date().toISOString()
      };

      // TODO: Persist `message` to PostgreSQL via transactional outbox or direct insert
      // await db.messages.insert(message);

      // Broadcast to specific channel room
      io.to(data.channelId).emit('message:receive', message);
      
      // Acknowledge success to the sender
      if (typeof callback === 'function') {
        callback({ success: true, message });
      }
    });

    // --- 4. Typing Indicators ---
    socket.on('typing:start', (data) => {
      socket.to(data.channelId).emit('typing:update', { userId, channelId: data.channelId, isTyping: true });
    });

    socket.on('typing:stop', (data) => {
      socket.to(data.channelId).emit('typing:update', { userId, channelId: data.channelId, isTyping: false });
    });
    
    // --- 5. Channel Management ---
    socket.on('channel:join', (channelId) => {
      socket.join(channelId);
    });

    socket.on('channel:leave', (channelId) => {
      socket.leave(channelId);
    });
  });

  return io;
}
