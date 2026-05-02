# Code Protection & Safety Policy

## Overview
All work on this codebase is protected against accidental deletion or loss. This document outlines the protection mechanisms and best practices.

## Protections in Place

### 1. **Git Hooks - Pre-Commit Protection** ✅
- **File**: `.git/hooks/pre-commit`
- **Function**: Automatically detects and warns about significant code deletions
- **Rules**:
  - Warns if >10 lines deleted from any file
  - **Blocks** deletion of >5 lines from critical files (`calc_engine.py`, `index.html`, `api.py`)
  - Requires explicit `--no-verify` confirmation for critical file changes

### 2. **Version Control (GitHub)** ✅
- **URL**: https://github.com/macmikul/AASHTO_Concrete_App.git
- **Branch**: main
- **Backup**: All commits are stored remotely and recoverable
- **History**: Full commit history with detailed messages for code archaeology

### 3. **Commit Message Standards** 📝
Every commit includes:
- Clear description of changes
- Which files were modified
- Why changes were made
- Test verification status

**Example**:
```
Implement AASHTO 10th Ed Eq. 5.6.4.4-3 Pn_max formula with pure compression (c→∞)

- Updated Pn_max formula to: -0.80·[kc·f'c·(Ag-Ast-Aps) + fy·Ast - Aps·(fpe-Ep·εcu)]
- Pure compression key point now uses c→∞ with uniform ε=0.003 at all fibers
- All tests pass: test_fixes.py, test_multirow_pm.py, test_pt.py (22 passed)
```

## Development Workflow

### Before Making Changes
```bash
# Make sure you're on main and up to date
git checkout main
git pull origin main
```

### During Development
```bash
# Stage changes incrementally
git add <file>

# Git will warn about large deletions
# Review the warning carefully

# If warning is legitimate (intentional refactor):
git commit -m "Clear message describing why code was removed"
```

### Protecting Against Critical Deletions
```bash
# If you need to delete >5 lines from calc_engine.py, index.html, or api.py:
# 1. Commit will be blocked
# 2. Options:
#    a) Review why deletion is needed (always preferred)
#    b) Use explicit override: git commit --no-verify
```

### After Committing
```bash
# Always push to GitHub immediately
git push origin main

# Verify on GitHub: https://github.com/macmikul/AASHTO_Concrete_App
```

## Recovery Procedures

### If Code Was Accidentally Deleted
1. **View recent commits**:
   ```bash
   git log --oneline -10
   ```

2. **Restore a file from a previous commit**:
   ```bash
   git checkout <commit-hash> -- <filename>
   ```

3. **View what was deleted**:
   ```bash
   git show <commit-hash>:<filename>
   ```

4. **Revert an entire commit**:
   ```bash
   git revert <commit-hash>
   ```

### If You Need Help
- All changes are on GitHub with full history
- Contact team before doing large refactors
- Use `git diff` to review changes before committing

## Critical Files (Extra Protection)

These files require special care:
- **calc_engine.py** — Core calculation engine (1000+ lines)
- **index.html** — Main UI (4500+ lines)
- **api.py** — API bridge to frontend

Any deletion >5 lines will trigger protection. This ensures we:
- Never accidentally delete a critical function
- Have explicit confirmation for refactoring
- Keep audit trail of why changes were made

## Testing Before Commit

Always run tests before committing:
```bash
python test_fixes.py
python test_multirow_pm.py
python -m pytest test_pt.py -q
```

If tests pass, include in commit message:
```
All tests pass: test_fixes.py, test_multirow_pm.py, test_pt.py (22 passed)
```

## Questions?

For any questions about protecting code or recovering changes:
1. Check git log for history
2. Contact team lead
3. Review this document

---

**Last Updated**: May 1, 2026  
**Protection Level**: Full (Git hooks + GitHub backup + Commit standards)
