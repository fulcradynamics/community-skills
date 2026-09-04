# Fixture privacy policy

Every committed fixture must be synthetic or derived from an intentionally public,
redistributable example and must label its origin. M0 fixtures are synthetic only.

- Never copy user activity, repository names, issue text, commit text, URLs, or IDs
  from a real run into this repository.
- Never commit private repository evidence, even in a test failure snapshot.
- Never commit credentials, authorization headers, cookies, environment files, or
  account exports.
- Use reserved/example identities and obviously synthetic IDs. Keep
  `fixture_origin` and `contains_private_repository_data` metadata in JSON fixtures.
- Review fixture diffs as security-sensitive changes. Generated run artifacts belong
  outside the repository and must remain ignored.
