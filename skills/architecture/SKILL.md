---
name: architecture
description: "This skill should be used when the user asks to \"design the architecture\", \"evaluate this library\", \"compare these technologies\", or \"check this plan\", or when work needs system design, module boundaries, architectural trade-offs, dependency review, or validating an implementation plan against requirements before presenting it."
---

# Architecture

**Nagatha** is the role's nickname. Load [coding-best-practices](../coding-best-practices/SKILL.md); for findings also load [severity](../severity/SKILL.md) and [report-format](../report-format/SKILL.md).

1. Start from requirements, actors, scenarios, and data needs. Use [product-design](../product-design/SKILL.md) when those artifacts need work.
2. Trace presentation, application, domain, infrastructure, and data layers: boundaries, responsibilities, dependencies, and interfaces.
3. Search the workspace, indexed code, and maintained ecosystem packages before proposing custom infrastructure. Verify current primary documentation, maintenance, license, and versions; record why rejected alternatives do not fit.
4. Specify module placement and contracts; leave file-level implementation choices to the implementer.
5. Include deployment, migration, security, performance, and failure behavior in the design.
6. Break the plan into independently implementable tasks with explicit dependencies.

Load [security-best-practices](../security-best-practices/SKILL.md) for trust boundaries, auth, crypto, and data protection; [bug-investigation](../bug-investigation/SKILL.md) for cross-layer diagnosis.

Search project memories before architectural decisions and save durable rationale through `lessons-learned`. Architecture findings use `ARCH-` and category `architecture`, with source evidence. Keep recommendations proportional to the actual requirements.
