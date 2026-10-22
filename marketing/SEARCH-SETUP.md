# Search ownership and publication checklist

**Current update2026-10-22:** owner resumed setup. Google ownership is now
verified; sitemap submitted but Google reports Couldn't fetch, requiring diagnosis.
Bing pending. Earlier deferral/session-unavailable statements below are historical.
See [latest status](SEO-STATUS.md) and current guide checkpoint. AlternativeTo
currently excludes PDF suites; use [current eligibility](PLACEMENTS-2026-10-22.md).

Canonical site: https://pdf.praritsidana.com/. Brand: **Prarit Sidana PDF**.
Owner confirmed on 2026-10-22 that Google Search Console and Bing Webmaster Tools
have not been set up. No authenticated browser/account session is available to
this workspace. No registration, ownership verification or Google submission is
claimed here. Passwords and recovery codes are not needed by this repository.

## Google Search Console

1. Sign into the owner's real Google account at https://search.google.com/search-console/.
2. Add a URL-prefix property for `https://pdf.praritsidana.com/`. If the owner
   prefers a domain property, use the DNS TXT record Google supplies instead;
   do not change the site's existing A record.
3. For the URL-prefix property, choose HTML tag verification. Copy only the
   `content` token from `google-site-verification` into the private server
   environment as `GOOGLE_SITE_VERIFICATION`. Recreate only this app container,
   confirm the tag on the public homepage, then click Verify in Search Console.
4. Under Sitemaps, submit `https://pdf.praritsidana.com/sitemap.xml` once.
5. Inspect the homepage and one guide URL, then request indexing if eligible.
   Check the Page indexing and Performance reports after data becomes available.

## Bing Webmaster Tools

1. Sign in at https://www.bing.com/webmasters/. Import the verified Google
   property or add `https://pdf.praritsidana.com/` directly.
2. If using HTML meta verification, set only the `msvalidate.01` content token in
   `BING_SITE_VERIFICATION`, recreate this app, then click Verify.
3. Submit the same sitemap. Review crawl/indexing reports. IndexNow notifications
   are a separate mechanism and do not create a webmaster dashboard account.

Both environment hooks already exist. Leave tokens empty until provided by the
real accounts; fabricated tokens cannot establish ownership. Deployment commands
and isolation rules are in `deploy/hostinger/README.md`.

## Relevant external placements

Ready-to-use factual descriptions, an original article and announcements are in
[LAUNCH-KIT.md](LAUNCH-KIT.md). AlternativeTo, SaaSHub and Product Hunt submissions
require real account/email or editorial steps. Their drafts are **not submitted**.
Do not impersonate an independent reviewer, invent user counts or disguise product
promotion as a personal testimonial. DEV currently excludes this AI-assisted
promotional/backlink use; choose an eligible publication.

The repository README links directly to the live app and useful tools; it is one
project source referring domain, not multiple independently earned endorsements.
The four guides hosted on the product site are original published content and
internal links, not external backlinks. Paid placements, mass directory entries,
automated comments and link exchanges have not been purchased or created.

## Evidence and measurement

Record actual notification HTTP responses and actual public listing URLs in
`SEO-STATUS.md`. An HTTP 200/202 from IndexNow means notification acceptance;
it does not confirm crawling, indexing, Google inclusion or a ranking position.
Measure real indexed pages, search impressions, relevant referral visits and
completed document tasks once the owner has measurement access.

Official references: [Google sitemap guide](https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap),
[Search Console introduction](https://search.google.com/search-console/about),
[Google spam policies](https://developers.google.com/search/docs/essentials/spam-policies),
[Bing sitemaps](https://www.bing.com/webmasters/help/sitemaps-3b5cf6ed),
[IndexNow documentation](https://www.indexnow.org/documentation).
