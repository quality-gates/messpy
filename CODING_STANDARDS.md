# Coding standards

- Strongly prefer integration tests over unit tests
- Strongly prefer exercising real system behaviour over 'the tests pass so it must work'
- Only mock third party services we can't control
- Code comments only use Simplified Technical English grounded in CONTEXT.md's domain language

## Common footguns to avoid

- Tautological tests and mocks of services we own
- 'The tests pass so it must work' over 'Does it actually work as a user would expect?' 
- README.md files and code comments that include brittle references likely and perfectly acceptable to change over time
- Code comments that just repeat what the code already makes clear
