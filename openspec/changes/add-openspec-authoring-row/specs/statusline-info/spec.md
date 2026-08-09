## ADDED Requirements

### Requirement: Authoring-change gather field

The openspec gather source SHALL, in the same pass that discovers task-bearing
changes, additionally enumerate change directories under `openspec/changes/` that
have no `tasks.md`, and expose them as a separate collection carrying, per
change: the directory name, whether `proposal.md` exists, whether `design.md`
exists, the count of `specs/*/spec.md` files, and the declared delta total parsed
from `proposal.md`.

The two collections SHALL be disjoint by construction: a change directory
contributes to exactly one of them, decided by the presence of `tasks.md`. The
existing task-bearing collection's element shape SHALL be unchanged, so existing
call sites are unaffected.

`SessionView` SHALL expose the new collection through a cached property alongside
the existing one, and reading either SHALL trigger the openspec walk at most once
per view.

#### Scenario: Disjoint collections

- **WHEN** the changes directory holds one change with a populated `tasks.md` and
  one with none
- **THEN** the first appears only in the task-bearing collection and the second
  only in the authoring collection

#### Scenario: Existing shape preserved

- **WHEN** the gather source is read in a repo with only task-bearing changes
- **THEN** the task-bearing collection is identical to what it was before this
  change, and the authoring collection is empty

#### Scenario: Single walk feeds both properties

- **WHEN** both the task-bearing and the authoring properties are read on one
  `SessionView`
- **THEN** the openspec directory is walked exactly once

#### Scenario: Laziness preserved

- **WHEN** a narrow-width build reads only the subagent source from a `SessionView`
- **THEN** the openspec walk — including the new changes-directory enumeration —
  is not triggered

#### Scenario: Pure read

- **WHEN** the authoring collection is gathered
- **THEN** no file under `openspec/` is created, modified or deleted
