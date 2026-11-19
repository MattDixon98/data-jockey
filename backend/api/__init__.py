"""Both public APIs over the serving snapshot, read-only.

- queries.py: the shared query layer both APIs build on, so they can't disagree.
- graphql/: Strawberry, at /graphql/.
- rest/: Django REST Framework, at /api/v1/.
- tests/: one in-memory test snapshot (tests/snapshot.py) and a suite per API.
"""
