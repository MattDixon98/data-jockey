"""The public GraphQL API over the serving snapshot (read-only, no mutations).

Strawberry (strawberry-graphql-django) types over the racing models, served at
/graphql/ (GraphiQL in a browser). Every query reads the snapshot database;
the optimizer extension turns nested fields into select_related/prefetch_related,
so a racecard is a handful of queries however many runners it has.
"""
