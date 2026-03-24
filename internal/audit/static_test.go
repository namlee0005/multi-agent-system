package audit_test

// Static analysis tests — FAST (<1s).
// These scan the Go source tree for forbidden imports and path strings.
// Run: go test ./internal/audit/...

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// rootDir walks up from the test file to find the module root.
func rootDir(t *testing.T) string {
	t.Helper()
	dir, err := os.Getwd()
	if err != nil {
		t.Fatalf("getwd: %v", err)
	}
	// Walk upward until we find go.mod
	for {
		if _, err := os.Stat(filepath.Join(dir, "go.mod")); err == nil {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			// No go.mod found; fall back to cwd (acceptable in tests)
			wd, _ := os.Getwd()
			// Go up two levels from internal/audit
			return filepath.Join(wd, "..", "..")
		}
		dir = parent
	}
}

// collectGoFiles returns all .go file paths under root (excluding vendor).
func collectGoFiles(t *testing.T, root string) []string {
	t.Helper()
	var files []string
	err := filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		// Skip vendor, .git, node_modules
		base := filepath.Base(path)
		if info.IsDir() && (base == "vendor" || base == ".git" || base == "node_modules") {
			return filepath.SkipDir
		}
		if !info.IsDir() && strings.HasSuffix(path, ".go") {
			files = append(files, path)
		}
		return nil
	})
	if err != nil {
		t.Fatalf("walk: %v", err)
	}
	return files
}

// ─── Single-DB enforcement ────────────────────────────────────────────────

// TestNoPostgresImport verifies no Go file imports a PostgreSQL driver.
// Revision 3 mandates MongoDB as the sole database.
func TestNoPostgresImport(t *testing.T) {
	// FAST (<1s)
	root := rootDir(t)
	forbidden := []string{
		"database/sql",
		"lib/pq",
		"jackc/pgx",
		"go-pg/pg",
		"uptrace/bun",
		"jmoiron/sqlx",
	}
	files := collectGoFiles(t, root)
	for _, path := range files {
		content, err := os.ReadFile(path)
		if err != nil {
			t.Fatalf("read %s: %v", path, err)
		}
		for _, pkg := range forbidden {
			if strings.Contains(string(content), pkg) {
				t.Errorf("PostgreSQL import %q found in %s — Revision 3 mandates MongoDB only", pkg, path)
			}
		}
	}
}

// TestNoRedisImport verifies no Go file imports a Redis client.
// Revision 2 eliminated Redis; Revision 3 confirmed removal.
func TestNoRedisImport(t *testing.T) {
	// FAST (<1s)
	root := rootDir(t)
	forbidden := []string{
		"go-redis/redis",
		"gomodule/redigo",
		"redis/go-redis",
	}
	files := collectGoFiles(t, root)
	for _, path := range files {
		content, err := os.ReadFile(path)
		if err != nil {
			t.Fatalf("read %s: %v", path, err)
		}
		for _, pkg := range forbidden {
			if strings.Contains(string(content), pkg) {
				t.Errorf("Redis import %q found in %s — Redis was eliminated in Revision 2", pkg, path)
			}
		}
	}
}

// TestNoBaseProjectPathLeakage verifies no file contains the literal string
// "base-project/" which would indicate a stale template path.
func TestNoBaseProjectPathLeakage(t *testing.T) {
	// FAST (<1s)
	root := rootDir(t)
	files := collectGoFiles(t, root)

	// Also scan non-Go files likely to contain paths (yaml, proto, md)
	var allFiles []string
	allFiles = append(allFiles, files...)
	for _, ext := range []string{".yaml", ".yml", ".proto", ".md", ".json"} {
		err := filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
			if err != nil {
				return err
			}
			base := filepath.Base(path)
			if info.IsDir() && (base == "vendor" || base == ".git") {
				return filepath.SkipDir
			}
			if !info.IsDir() && strings.HasSuffix(path, ext) {
				allFiles = append(allFiles, path)
			}
			return nil
		})
		if err != nil {
			t.Fatalf("walk for %s: %v", ext, err)
		}
	}

	for _, path := range allFiles {
		content, err := os.ReadFile(path)
		if err != nil {
			continue // skip unreadable files
		}
		if strings.Contains(string(content), "base-project/") {
			t.Errorf("stale template path 'base-project/' found in %s", path)
		}
	}
}

// TestAllGoFilesHavePackageDeclaration verifies no truncated file exists.
func TestAllGoFilesHavePackageDeclaration(t *testing.T) {
	// FAST (<1s)
	root := rootDir(t)
	files := collectGoFiles(t, root)
	for _, path := range files {
		content, err := os.ReadFile(path)
		if err != nil {
			t.Fatalf("read %s: %v", path, err)
		}
		if !strings.Contains(string(content), "package ") {
			t.Errorf("file %s has no package declaration — may be truncated", path)
		}
	}
}

// TestMongoDriverImportedInRepo verifies the MongoDB driver is actually imported
// in the repository package (guards against accidental removal).
func TestMongoDriverImportedInRepo(t *testing.T) {
	// FAST (<1s)
	root := rootDir(t)
	repoDir := filepath.Join(root, "internal", "repository")
	files, err := filepath.Glob(filepath.Join(repoDir, "*.go"))
	if err != nil || len(files) == 0 {
		t.Skip("repository package not yet created")
	}
	found := false
	for _, path := range files {
		content, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		if strings.Contains(string(content), "go.mongodb.org/mongo-driver") {
			found = true
			break
		}
	}
	if !found {
		t.Error("go.mongodb.org/mongo-driver not imported in internal/repository — MongoDB may have been replaced")
	}
}
