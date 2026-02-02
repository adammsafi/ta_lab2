---
title: "Memory Model"
author: "Adam Safi"
created: 2026-01-14T14:17:00+00:00
modified: 2026-01-14T14:21:00+00:00
original_path: "C:\Users\asafi\Documents\ProjectTT\Features\Memory\Memory Model.docx"
original_size_bytes: 21541
---
**Memory Model & Contract**

**ta\_lab2 – Canonical Memory Specification**

**1. Purpose**

This document defines the **memory system** for
ta\_lab2.

Memory is treated as a **first-class architectural
component**, equivalent in importance to:

* time (dim\_timeframe, dim\_sessions)
* data contracts (snapshot invariants)
* schema governance

The goal is to ensure that:

* LLM usage is **consistent, auditable, and
  deterministic**
* Knowledge does not silently drift across conversations
* Decisions, invariants, and definitions have a single source of
  truth
* Retrieval systems assist reasoning but **do not define
  truth**

**2. What “Memory” Means in This Project**

In ta\_lab2, **memory is not chat history**.

Memory is:

* Persistent knowledge extracted from interactions, documents, and
  code
* Structured, versioned, and conflict-aware
* Explicitly scoped and status-controlled

Memory includes:

* Architectural decisions
* Definitions (time, bars, EMAs, contracts)
* Invariants and non-negotiables
* Naming conventions
* Project goals and constraints
* Long-lived user preferences relevant to the system

Memory does **not** include:

* Raw conversation logs
* Ephemeral brainstorming
* Intermediate reasoning
* Temporary plans
* Unvalidated assumptions

**3. Design Principles**

**3.1 Memory is Explicit**

Nothing is “implicitly remembered.”  
All memory must exist as a structured item with metadata.

**3.2 Memory Has Status**

Every memory item is one of:

* **active** – currently authoritative
* **superseded** – replaced by a newer item
* **deprecated** – intentionally retained but
  discouraged
* **rejected** – explicitly false or invalid
* **uncertain** – captured but not yet
  validated

Only **active** memory is considered authoritative.

**3.3 Memory is Append-Only at the Event Level**

Raw memory ingestion is append-only.  
Resolution happens through status changes, not deletion.

This preserves history and allows audits.

**3.4 Memory is Deterministic**

Re-extracting the same memory should:

* resolve to the same identity
* not create duplicates
* update status or confidence if needed

**4. Memory Item Contract**

Every memory item MUST satisfy the following schema.

**Required Fields**

* **id**  
  Stable, deterministic identifier  
  (e.g., hash of normalized content + scope + type)
* **type**  
  One of:

  + fact
  + definition
  + decision
  + invariant
  + constraint
  + preference
  + plan
  + glossary\_term
* **scope**  
  Where this memory applies:

  + project
  + module
  + file
  + pipeline
  + CLI
  + test
  + person
* **content**  
  Canonical, normalized statement of the memory
* **source**  
  Pointer to origin:

  + conversation id
  + document path
  + commit hash
  + script path
* **timestamp**  
  When the memory was asserted or extracted
* **status**  
  active | superseded | deprecated | rejected | uncertain

**Optional Fields**

* **confidence**  
  explicit | inferred | uncertain
* **tags**  
  Freeform, but consistent  
  Examples:

  + time\_model
  + bars
  + ema
  + memory\_system
  + contracts
  + pipelines
* **supersedes**  
  ID(s) of memory items this replaces

**5. Canonical Storage vs Derived Views**

**5.1 Canonical Store (Source of Truth)**

The following are **authoritative**:

memory/

├── 00\_inbox/ # raw extracted candidates

├── 01\_normalized/ # append-only memory events (JSONL)

├── 02\_extracted/ # resolved active memory set

└── \_reports/

* Canonical data is **git-tracked**
* Human-readable and diffable
* Suitable for audits and reviews

**5.2 Derived Stores (Non-Authoritative)**

These are **indexes or views**, not truth:

* Vector databases (mem0 / Qdrant)
* Markdown summaries
* LLM prompt context
* Search caches

They may be rebuilt at any time from canonical memory.

**6. Memory Audits & Integrity Checks**

Memory is subject to automated checks, similar to data integrity
tests.

Minimum required checks:

* **Duplicate detection –** Same content, different
  IDs
* **Conflict detection –** Two active items that
  contradict
* **Orphan detection –** Missing or invalid source
  reference
* **Supersession enforcement –** Only one active
  memory per invariant/decision key
* **Staleness detection –** Old active items flagged
  for review

No memory snapshot is considered valid unless all checks pass.

**7. Relationship to LLM Usage**

LLMs:

* May retrieve memory
* May propose new memory
* May reason over memory

LLMs:

* Do **not** decide what is authoritative
* Do **not** override status
* Do **not** resolve conflicts automatically

All memory resolution is explicit and reviewable.

**8. Non-Goals**

This system explicitly does **not** aim to:

* Store full chat transcripts as memory
* Recreate human autobiographical memory
* Automatically infer truth from frequency
* Optimize for emotional or conversational continuity

It optimizes for:

* correctness
* stability
* reproducibility
* long-term project coherence

**9. Guiding Analogy**

Time without a model causes silent bugs.  
Memory without a model causes silent drift.

This document exists to prevent both.

**10. Status of This Document**

This document is:

* **Foundational**
* **Normative**
* **Precedes implementation details**

Any implementation that violates this contract is incorrect by
definition.