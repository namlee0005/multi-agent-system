import re

file_path = '/home/ben/project/projects/mm-platform-bot/internal/engine/executor.go'
with open(file_path, 'r') as f:
    content = f.read()

# Fix the executeRecalc / Executor.Execute async race condition
# We modify Executor to drop events if busy instead of queueing them in runAsync

# In executor.go
old_runAsync = """func (ex *Executor) runAsync(ctx context.Context, fn func() error) {
	select {
	case ex.execGate <- struct{}{}:
		go func() {
			defer func() { <-ex.execGate }()
			if err := fn(); err != nil {
				log.Printf("[EXECUTOR] Execution failed: %v", err)
			}
		}()
	default:
		// Wait briefly for previous execution to finish
		select {
		case ex.execGate <- struct{}{}:
			go func() {
				defer func() { <-ex.execGate }()
				if err := fn(); err != nil {
					log.Printf("[EXECUTOR] Execution failed: %v", err)
				}
			}()
		case <-time.After(2 * time.Second):
			log.Printf("[EXECUTOR] Skipped — previous execution still running after 2s")
		}
	}
}"""

new_runAsync = """func (ex *Executor) runAsync(ctx context.Context, fn func() error) {
	select {
	case ex.execGate <- struct{}{}:
		go func() {
			defer func() { <-ex.execGate }()
			if err := fn(); err != nil {
				log.Printf("[EXECUTOR] Execution failed: %v", err)
			}
		}()
	default:
		// DROP PATTERN: If executor is currently busy flying orders, completely drop this tick's execution.
		// The next tick will re-evaluate based on fresh state.
		log.Printf("[EXECUTOR] Dropped — previous execution still flying orders")
	}
}"""

content = content.replace(old_runAsync, new_runAsync)

with open(file_path, 'w') as f:
    f.write(content)

