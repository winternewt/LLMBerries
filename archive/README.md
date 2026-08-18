# Archive

This folder contains outdated design documents from before the Command Pattern refactor.

## Archived Documents

### DESIGN_OLD.md (originally DESIGN.md)
**Date Archived:** 2025-11-07  
**Reason:** Original OOP design document. No longer reflects current architecture.  
**Status:** Historical reference only

**What it contained:**
- Original turn-based system design
- OOP class structure (AgentBody with direct mutations)
- Communication flow pre-Command Pattern
- Turn scheduling with time_until_turn

**Why archived:**
- Architecture changed to Command Pattern
- Circular dependencies existed in that design
- WORLD singleton pattern (anti-pattern)
- Mixed agent state with LLM logic

---

### ARCHITECTURE_SUMMARY.md
**Date Archived:** 2025-11-07  
**Reason:** Partial summary that's now incorporated into NEW_DESIGN.md  
**Status:** Superseded

**What it contained:**
- "Frozen Class + Rules in Same Module" pattern
- Command Pattern overview
- File organization
- Key principles

**Why archived:**
- Content merged into NEW_DESIGN.md
- Incomplete (claimed refactor was done, but it wasn't)
- NEW_DESIGN.md is now single source of truth

---

### pattern_refactor.md
**Date Archived:** 2025-11-07  
**Reason:** Detailed refactor plan, still useful as reference  
**Status:** Reference document (keep for historical reasoning)

**What it contains:**
- Lessons learned from original OOP approach
- Reasoning behind Command Pattern choice
- Implementation decisions (Pydantic vs pyrsistent, etc.)
- Memory overhead analysis
- Detailed migration plan by module
- Phase-by-phase refactoring checklist

**Why archived:**
- Refactor is in progress (not complete)
- Some sections outdated as refactor evolved
- NEW_DESIGN.md contains current state and next steps
- Still valuable for understanding *why* decisions were made

**Note:** This document is worth reading for anyone wondering "Why Command Pattern?" or "Why immutability?"

---

## What to Read Instead

- **NEW_DESIGN.md** - Current state, architecture, and roadmap (single source of truth)
- **game_patterns.md** - Architecture patterns reference (unchanged)
- **README.md** - Project overview and quick start

---

## Historical Context

These documents represent the evolution of LLMBerries from:
1. **Initial OOP design** (DESIGN_OLD.md)
2. **Recognition of architectural issues** (pattern_refactor.md)
3. **Decision to use Command Pattern** (pattern_refactor.md)
4. **Partial refactor** (ARCHITECTURE_SUMMARY.md)
5. **Current comprehensive design** (NEW_DESIGN.md) ✅

The refactor is ongoing. See `NEW_DESIGN.md` for current priorities and todos.

