# Version 25.0

## Graph API

**Released** February 18, 2026 | **Available until** TBD | [Blog post](/blog/post/2026/02/18/introducing-graph-api-v25-and-marketing-api-v25/)

### Insights

*Will apply to all versions when v26.0 is released.*

When v26.0 is released later this year, page reach, page post reach, video impressions, and story impressions metrics listed below will be deprecated. Once deprecated, these metrics will return an error if requested using any API version.

Alternative metrics are listed in parenthesis. If a metric has no alternative, data that the metric would normally return will no longer be available upon deprecation.

#### Page Insights API

Removing the following [Page Insights API](/docs/graph-api/reference/v24.0/insights) metrics:

* `page_impressions_unique` (use `page_total_media_view_unique` to get total unique views on a page's media, and `page_media_view` to get breakdowns between paid and organic reach on a page's media)
* `page_impressions_paid_unique`
* `page_impressions_viral_unique`
* `page_impressions_nonviral_unique`
* `page_posts_impressions`
* `page_posts_impressions_unique`
* `page_posts_impressions_paid`
* `page_posts_impressions_paid_unique`
* `page_posts_impressions_organic_unique`
* `page_posts_served_impressions_organic_unique`
* `page_posts_impressions_viral`
* `page_posts_impressions_viral_unique`
* `page_posts_impressions_nonviral`
* `page_posts_impressions_nonviral_unique`
* `page_video_views_unique`

#### Post Insights API

Removing the following [Post Insights API](/docs/graph-api/reference/v24.0/insights) metrics:

* `post_impressions_unique` (use `post_total_media_view_unique` to get total unique views on a page post media, and `post_media_view` to get breakdowns between paid and organic reach on a page post's media)
* `post_impressions_paid_unique`
* `post_impressions_fan_unique`
* `post_impressions_organic_unique`
* `post_impressions_viral_unique`
* `post_impressions_nonviral_unique`
* `post_impressions_nonviral_unique`
* `post_video_views_organic_unique`
* `post_video_views_paid_unique`
* `post_video_views_unique`

#### Video Insights API

Removing the following [Video Insights API](/docs/graph-api/reference/video/video_insights/) metrics:

* `post_impressions_unique`
* `total_video_impressions`
* `total_video_impressions_unique`
* `total_video_impressions_paid_unique`
* `total_video_impressions_paid`
* `total_video_impressions_organic_unique`
* `total_video_impressions_organic`
* `total_video_impressions_viral_unique`
* `total_video_impressions_viral`
* `total_video_impressions_fan_unique`
* `total_video_impressions_fan`
* `total_video_impressions_fan_paid_unique`
* `total_video_impressions_fan_paid`
* `total_video_views_organic_unique`
* `total_video_views_paid_unique`
* `total_video_views_unique`

#### Stories Insights API

Removing the following [Stories Insights API](/docs/graph-api/reference/stories/insights/) metrics:

* `PAGE_STORY_IMPRESSIONS_BY_STORY_ID` (use `STORY_MEDIA_VIEW` to get breakdowns between paid and organic reach on a story's media)
* `PAGE_STORY_IMPRESSIONS_BY_STORY_ID_UNIQUE` (use `STORY_TOTAL_MEDIA_VIEW_UNIQUE` to get total unique views on a story's media)

### Node metadata

*Applies to v25.0+. Will apply to all versions May 19, 2026.*

The [metadata query parameter](/docs/graph-api/overview/#node-metadata) (`metadata=1`) is deprecated and will no longer return metadata about supported fields for the targeted node. Use the Graph API Explorer or API references instead.

### Webhooks mTLS

The current Webhooks mTLS certificate is signed by the DigiCert root CA. Because DigiCert is [deprecating the use of the Client Authentication EKU](https://l.facebook.com/l.php?u=https%3A%2F%2Fknowledge.digicert.com%2Falerts%2Fsunsetting-client-authentication-eku-from-digicert-public-tls-certificates&h=AUAeNqk0PSRaDAkvy7zJNykTxi66yvzTctw1V2ywaGQQa2g4PXbU6rTA7TKqTeRQ-zJs3JZDAKhzVZmhFxgK6vzKb1Ffvd1NOdfQmAiK7JJHGhcfIFx23SEfqBmaI3mFvAv-2vztqVvCrOQe), the certificate cannot be renewed when the root CA expires on April 15, 2025.

Consequently, starting March 31, 2026, Meta will sign a new Webhooks mTLS certificate using a different Certificate Authority (CA), owned by Meta. It will maintain the same common name (`client.webhooks.fbclientcerts.com`) as the current certificate.

If your servers are configured to require and verify the Webhooks mTLS certificate, you must trust the new Meta CA. Failure to update your trust store by March 31, 2026, will result in TLS handshake failures, and your servers will stop receiving all webhooks events.

To ensure a seamless transition, download the new meta-outbound-api-ca-2025-12.pem root certificate and add it to your trust store as soon as possible. You can do this while the current certificate is active. Do not wait until the deadline, or you risk an interruption to webhook receipt and delivery.

## Marketing API

February 18, 2026 | **Available until** TBD | [Blog post](/blog/post/2026/02/18/introducing-graph-api-v25-and-marketing-api-v25)

### Advantage+ Campaigns

#### Advantage+ Shopping Campaigns and Advantage+ App Campaigns deprecation

*Applies to v25.0+. Will apply to all versions May 19, 2026.*

Creation, duplication, and updates to [Advantage+ shopping campaigns](/docs/marketing-api/advantage-shopping-campaigns) and [Advantage+ app campaigns](docs/app-ads/advantage-app-campaigns/) is no longer allowed.

Refer to the [Advantage+ Campaigns documentation](/docs/marketing-api/advantage-campaigns) to learn how to [migrate your campaigns](/docs/marketing-api/advantage-campaigns/#migrate-advatage--shopping-campaigns-and-advantage--app-campaigns-into-advantage--campaigns) to Advantage+ campaigns or continue to create new campaigns using the Advantage+ structure.

The following endpoints are affected:

* [`POST /{ad-account-id}/campaigns`](/docs/marketing-api/reference/ad-account/campaigns/)
* [`POST /{campaign-id}/copies`](/docs/marketing-api/reference/ad-campaign-group/copies/)

### Insights

#### Asynchronous Jobs

*Applies to v25.0+.*

The following new default fields will be returned when an asynchronous ad report fails:

* `error_code`: The error code
* `error_message`: A message corresponding to the `error_code`
* `error_subcode`: The specific subcode for the error
* `error_user_title`: A user-friendly title for the error subcode
* `error_user_msg`: A user-friendly message detailing the error subcode

For any developers with access to the `error_code` field, the type will be changed from `uint` to `int`.

See [Insights API Asynchronous Jobs](/docs/marketing-api/insights/best-practices#asynchronous) and [Ads Insights API Error Codes](/docs/marketing-api/insights/error-codes) for more information.

The following endpoints are affected:

* [`GET /{ad-report-run-id}`](/docs/marketing-api/reference/ad-report-run)
