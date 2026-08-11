# Rule applicability

## ConstructorWithNameAsEnclosingClass

Python has no separately named constructor declaration. This shared rule remains loadable for policy compatibility and emits no findings.

## GotoStatement

Python has no goto statement. This shared rule remains loadable through `design` and custom rulesets for policy compatibility and emits no findings.

## Strict Python naming adaptations

The `controversial` ruleset retains the stable family identities `CamelCaseClassName`, `CamelCaseMethodName`, `CamelCasePropertyName`, `CamelCaseParameterName`, and `CamelCaseVariableName` in configuration and reports. For Python, `CamelCaseClassName` means CapWords class names; the other four identities mean role-appropriate `snake_case`, including conventional underscores between words.

Leading-underscore private names, dunder names, conventional parameters such as `self`, `cls`, `*args`, and `**kwargs`, constants, and type-parameter declarations are exempt. A trailing underscore used to avoid a keyword is accepted. Computed attribute names are not guessed. The shared `allow-underscore` and `allow-underscore-test` properties remain loadable with their family defaults for policy compatibility; they do not disable underscores required by Python `snake_case`.
