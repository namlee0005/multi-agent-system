package repository

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/shopspring/decimal"
	"go.mongodb.org/mongo-driver/bson"
	"go.mongodb.org/mongo-driver/bson/primitive"
	"go.mongodb.org/mongo-driver/mongo"
	"go.mongodb.org/mongo-driver/mongo/options"
)

// ─── MongoBotConfigRepo ───────────────────────────────────────────────────

type MongoBotConfigRepo struct{ coll *mongo.Collection }

func NewMongoBotConfigRepo(db *mongo.Database) *MongoBotConfigRepo {
	return &MongoBotConfigRepo{coll: db.Collection("bot_configs")}
}

func (r *MongoBotConfigRepo) Insert(ctx context.Context, cfg *BotConfig) error {
	cfg.CreatedAt = time.Now().UTC()
	_, err := r.coll.InsertOne(ctx, cfg)
	return err
}

func (r *MongoBotConfigRepo) FindByBotID(ctx context.Context, botID string) (*BotConfig, error) {
	var cfg BotConfig
	err := r.coll.FindOne(ctx, bson.M{"bot_id": botID}).Decode(&cfg)
	if errors.Is(err, mongo.ErrNoDocuments) {
		return nil, ErrNotFound
	}
	return &cfg, err
}

func (r *MongoBotConfigRepo) Update(ctx context.Context, cfg *BotConfig) error {
	res, err := r.coll.ReplaceOne(ctx, bson.M{"bot_id": cfg.BotID}, cfg)
	if err != nil {
		return err
	}
	if res.MatchedCount == 0 {
		return ErrNotFound
	}
	return nil
}

func (r *MongoBotConfigRepo) Delete(ctx context.Context, botID string) error {
	res, err := r.coll.DeleteOne(ctx, bson.M{"bot_id": botID})
	if err != nil {
		return err
	}
	if res.DeletedCount == 0 {
		return ErrNotFound
	}
	return nil
}

// ─── MongoSessionRepo ─────────────────────────────────────────────────────

type MongoSessionRepo struct{ coll *mongo.Collection }

func NewMongoSessionRepo(db *mongo.Database) *MongoSessionRepo {
	return &MongoSessionRepo{coll: db.Collection("active_sessions")}
}

func (r *MongoSessionRepo) Upsert(ctx context.Context, s *ActiveSession) error {
	s.UpdatedAt = time.Now().UTC()
	_, err := r.coll.UpdateOne(ctx,
		bson.M{"bot_id": s.BotID},
		bson.M{"$set": s},
		options.Update().SetUpsert(true),
	)
	return err
}

func (r *MongoSessionRepo) FindByBotID(ctx context.Context, botID string) (*ActiveSession, error) {
	var s ActiveSession
	err := r.coll.FindOne(ctx, bson.M{"bot_id": botID}).Decode(&s)
	if errors.Is(err, mongo.ErrNoDocuments) {
		return nil, ErrNotFound
	}
	return &s, err
}

func (r *MongoSessionRepo) SetState(ctx context.Context, botID string, state BotState) error {
	res, err := r.coll.UpdateOne(ctx,
		bson.M{"bot_id": botID},
		bson.M{"$set": bson.M{"state": state, "updated_at": time.Now().UTC()}},
	)
	if err != nil {
		return err
	}
	if res.MatchedCount == 0 {
		return ErrNotFound
	}
	return nil
}

func (r *MongoSessionRepo) Delete(ctx context.Context, botID string) error {
	res, err := r.coll.DeleteOne(ctx, bson.M{"bot_id": botID})
	if err != nil {
		return err
	}
	if res.DeletedCount == 0 {
		return ErrNotFound
	}
	return nil
}

// ─── MongoTradeRepo ───────────────────────────────────────────────────────

type MongoTradeRepo struct{ coll *mongo.Collection }

func NewMongoTradeRepo(db *mongo.Database) *MongoTradeRepo {
	return &MongoTradeRepo{coll: db.Collection("trade_history")}
}

func (r *MongoTradeRepo) Insert(ctx context.Context, rec *TradeRecord) error {
	rec.Timestamp = time.Now().UTC()
	_, err := r.coll.InsertOne(ctx, rec)
	return err
}

func (r *MongoTradeRepo) FindByBotID(ctx context.Context, botID string, limit int) ([]TradeRecord, error) {
	cur, err := r.coll.Find(ctx, bson.M{"bot_id": botID},
		options.Find().SetSort(bson.D{{Key: "timestamp", Value: -1}}).SetLimit(int64(limit)),
	)
	if err != nil {
		return nil, err
	}
	var out []TradeRecord
	return out, cur.All(ctx, &out)
}

// DrawdownSince returns net loss (positive = drawdown) since the given time.
func (r *MongoTradeRepo) DrawdownSince(ctx context.Context, botID string, since time.Time) (decimal.Decimal, error) {
	cur, err := r.coll.Find(ctx, bson.M{
		"bot_id":     botID,
		"event_type": "fill",
		"timestamp":  bson.M{"$gte": since},
	})
	if err != nil {
		return decimal.Zero, err
	}
	var recs []TradeRecord
	if err := cur.All(ctx, &recs); err != nil {
		return decimal.Zero, err
	}
	net := decimal.Zero
	for _, rec := range recs {
		pnl := rec.Price.Mul(rec.Quantity)
		if rec.Side == "sell" {
			net = net.Add(pnl)
		} else {
			net = net.Sub(pnl)
		}
	}
	if net.IsNegative() {
		return net.Neg(), nil
	}
	return decimal.Zero, nil
}

// ─── MongoAuditRepo ───────────────────────────────────────────────────────

type MongoAuditRepo struct{ coll *mongo.Collection }

func NewMongoAuditRepo(db *mongo.Database) *MongoAuditRepo {
	return &MongoAuditRepo{coll: db.Collection("audit_logs")}
}

func (r *MongoAuditRepo) Insert(ctx context.Context, log *AuditLog) error {
	log.ID = primitive.NewObjectID()
	log.Timestamp = time.Now().UTC()
	_, err := r.coll.InsertOne(ctx, log)
	return err
}

func (r *MongoAuditRepo) FindByBotID(ctx context.Context, botID string, limit int) ([]AuditLog, error) {
	cur, err := r.coll.Find(ctx, bson.M{"bot_id": botID},
		options.Find().SetSort(bson.D{{Key: "timestamp", Value: -1}}).SetLimit(int64(limit)),
	)
	if err != nil {
		return nil, fmt.Errorf("audit find: %w", err)
	}
	var out []AuditLog
	return out, cur.All(ctx, &out)
}
