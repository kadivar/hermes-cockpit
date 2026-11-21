---
name: platform-map
description: Write the conceptual platform map for this pack. Areas and features a person can do, with code anchors across repos. Then cockpit map build.
---

# Platform map

The Platform page draws `platform/map.yaml` next to `pack.yaml`. It is a model of what the product lets a person do, and which code across repositories does that. It is not a list of repositories.

Do this when the page is empty, when `cockpit map check` reports misses, or when the human asks to refresh the map.

1. Read the binding (`~/.hermes/cockpit.yaml`) and the pack it names. Read `repos.yaml` for each repo's `name` and `path`.
2. Read the product's own docs and the code those paths point at. Group by the job a person does (place an order, run a shift, manage a team). One area per job family. One feature per thing that person can finish.
3. A feature's `user` is one sentence in that person's words. `hld` is one sentence on which code does it. `anchors` name every repo that implements it. Paths are repo-relative globs: `**` crosses directories, `*` stays in one segment. A directory glob covers the files under it.
4. A component is machinery several features share (a queue, a login, a gateway). Features list it in `depends`. The component lists them in `used_by`. Every id is unique. Every reference is an id in this file.
5. `repos` lists the repo names the anchors use. Do not add an area called Repos. Do not make a feature whose only content is a repository name.
6. Write `platform/map.yaml` beside `pack.yaml`. Then run `cockpit map build` and `cockpit map check`.
7. A miss means the glob matches nothing in the local clone. Narrow it or remove it. Do not leave a miss to "fix later".
8. Do not copy a map from another product. Anchors must be paths you opened.

Schema:

```yaml
version: 1
repos: [api, web]
areas:
  - id: orders
    title: Orders
    summary: A customer places an order and can look it up later.
    features:
      - id: place-order
        title: Place an order
        user: Submits a basket and gets a confirmation.
        hld: The web checkout calls the order route on the api.
        anchors:
          - { repo: api, paths: ["orders/**"] }
          - { repo: web, paths: ["checkout/**"] }
        depends: [queue]
components:
  - id: queue
    title: Job queue
    summary: Work that continues after the response.
    hld: Background jobs on the api.
    anchors:
      - { repo: api, paths: ["jobs/**"] }
    used_by: [place-order]
```

The example is only a shape. Replace every id, sentence, and path with this pack's product.
