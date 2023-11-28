---
title: 'StarHead API Issues'
alt_titles:
  - 'StarHead does not work'
  - 'StarHead connection issues'
  - 'StarHead errors'
  - 'StarHead'
---

## I get errors on start before I can say anything or I get weird connection errors

Are you using Cloudflare DNS?

Try `nslookup https://api-test.star-head.de` in your terminal. If `Adress` is `1.1.1.1`, then you are.

If so, for now you can either change your DNS to something else (`8.8.8.8` is Google) or have to disable :wingman_ai: StarHead, sorry. We'll report this to the StarHead backend team.

## I get occasional errors

Please check the exact transcript text. Where there words misunderstood? Especially the API params `ship`, `location` or `money`?

We're aware of this issue and looking into it.
