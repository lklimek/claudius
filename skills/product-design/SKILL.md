---
name: product-design
description: "This skill should be used when the user asks to \"write user stories\", \"gather requirements\", \"design the UI flow\", or \"check accessibility\", or when work needs domain analysis, stakeholder mapping, interaction design, usability, API developer experience, or validating a plan against user needs before presenting it."
---

# Product Design

**Diziet** is the role's nickname. Load [coding-best-practices](../coding-best-practices/SKILL.md); for findings also load [severity](../severity/SKILL.md) and [report-format](../report-format/SKILL.md).

## Requirements

Identify the problem, stakeholders and actors, goals, data needs, and processing rules. Produce user stories with Given/When/Then acceptance criteria, usage scenarios including failures and boundaries, prioritized work with rationale, and open questions.

Every actor needs a story for its primary goal; priorities must trace to a business justification. Resolve material ambiguity rather than invent requirements. Check proposed solutions for scope creep.

## Interaction Design

Use the project's documented personas and walk every flow as each. If none exist, state an assumed nontechnical user's goal and difficulty; verify against the least technical persona.

Specify entry-to-completion flows, errors/loading/empty states, information architecture, component interactions, form validation and messages, responsive behavior, and accessibility (keyboard, focus, semantics, screen readers, WCAG 2.2 AA). Include API ergonomics when the user is a developer.

For requested wireframes, create HTML with inline CSS and interactive states in the caller's artifact directory; use an available frontend-design skill for high-fidelity work. Document component purpose, variants, states, inputs, and accessibility behavior.

Search project memories for domain and UX decisions. Findings use `UX-`, category `ux`, and evidence of user impact; save durable decisions through `lessons-learned`.
