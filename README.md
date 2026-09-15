# O System V1 — Clean People Build

This build uses a fresh O account layer with three people types.

## People
`/people` is the only O people entry point and presents exactly three choices:
- Rider
- Driver
- Mover

An Admin creates the account once. The person then selects their role and signs in with the same name and password. Phone or ID can also be used as the identifier when supplied.

## Admin
Admin control room: `/promise212324`
People management: `/promise212324/people`
Requests: `/promise212324/requests`

Set `USER_NAME`, `PASSWORD`, and `SECRET_KEY` in Render.

## Clean separation
The old account-management URLs are not defined in this build. The application uses a new `o.db` database file, so it does not reuse legacy account tables or legacy account routes.
