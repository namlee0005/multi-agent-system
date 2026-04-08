import re

file_path = '/home/ben/project/projects/mm-platform-bot/internal/engine/executor.go'
with open(file_path, 'r') as f:
    content = f.read()

old_runAsync = """// runAsync executes fn in a goroutine, serialized by execGate.
// Waits up to 2s for previous execution to finish before skipping.
func (ex *Executor) runAsync(ctx context.Context, fn func() error) {
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
		case <-ctx.Done():
		}
	}
}"""

new_runAsync = """// runAsync executes fn in a goroutine, serialized by execGate.
// DROP PATTERN: If previous execution is running, skips immediately.
func (ex *Executor) runAsync(ctx context.Context, fn func() error) {
	select {
	case ex.execGate <- struct{}{}:
		go func() {
			defer func() { <-ex.execGate }()
			if err := fn(); err != nil {
				log.Printf("[EXECUTOR] Execution failed: %v", err)
			}
		}()
	default:
		log.Printf("[EXECUTOR] Dropped — previous execution still flying orders")
	}
}"""

content = content.replace(old_runAsync, new_runAsync)

with open(file_path, 'w') as f:
    f.write(content)
