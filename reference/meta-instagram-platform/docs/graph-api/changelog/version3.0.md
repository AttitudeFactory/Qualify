# Version 3.0

[Graph API](#gapi) | [Marketing API](#mapi)

Changelog entries are categorized in the following way:

* **New Features** — New products or services, including new nodes, edges, and fields.
* **Changes** — Changes to existing products or services (not including **Deprecations**).
* **Deprecations** — Existing products or services that are being removed.
* **90-Day Breaking Changes** — Changes and deprecations that will take effect 90 days after the version release date.

**New Features**, **Changes**, and **Deprecations** only affect this version. **90-Day Breaking Changes** affect all versions.

[Breaking Changes](/docs/graph-api/changelog/breaking-changes) are not included here since they are not tied to specific releases.

---

## Graph API

**Released** May 1, 2018 | **Available until** July 28, 2020 | [Blog Post](https://developers.facebook.com/blog/post/2018/05/01/enhanced-developer-app-review-and-graph-api-3.0-now-live/)

* [New Features](#gapi-new)
* [Changes](#gapi-change)
* [Deprecations](#gapi-deprecate)
* [90-Day Breaking Changes](#gapi-90)

---

### New Features

* [Certificate Transparency](#certificate-transparency)
* [App Review](#new-app-review)
* [Pages API](#new-feature-pages-api)

#### Certificate Transparency

* **Phishing Alerts** — You can use the Certificate Transparency API's new `subscribed_domains_phishing` endpoint to [subscribe domains for phishing alerts](/docs/certificate-transparency#phishing-alerts).

#### App Review

* **Groups API** — You can use the new [Group API](/docs/apps/review/feature#reference-GROUPS_ACCESS) to access content in a Facebook Group. To use this API, you need two new permissions: [`groups_access_member_info`](/docs/facebook-login/permissions/#reference-groups_access_member_info) and [`publish_to_groups`](/docs/facebook-login/permissions/#reference-publish_to_groups).

#### Pages API

* **Page-Scoped ID API** — On April 24th, 2018, we announced that the Pages API now returns Page-scoped User IDs instead of App-scoped User IDs. We have released [a new, non-versioned API](/docs/pages/access-tokens/psid-api) for developers who need to map App-scoped IDs to their Page-scoped ID equivalents.

---

### Changes

* [App Review](#app-review)
* [Facebook Login](#login)
* [Comments Edge](#comments-edge)
* [Reading Edges and Fields](#reading)

#### App Review

* **Reviewable Permissions and Features** — We have significantly changed our App Review requirements, and as a result, many permissions and features now require App Review. To learn about these changes, please refer to our [App Review documentation](/docs/apps/review).

#### Comments Edge

* When read with a [User](/docs/facebook-login/access-tokens) access token, the `/comments` edge returns empty data for the following nodes:
  + [Album](/docs/graph-api/reference/album)
  + [Photo](/docs/graph-api/reference/photo)
  + [Post](/docs/graph-api/reference/post)
  + [Video](/docs/graph-api/reference/video)

#### Facebook Login

* [Access Token Expiration](https://developers.facebook.com/blog/post/2018/05/01/facebook-login-updates-further-protect-privacy/): An access tokens is invalid if the user hasn't engaged the app within the last 90 days.
* The following [default fields](/docs/facebook-login/permissions/?locale=en_US#reference-public_profile) have replaced public\_profile:
  + `id`
  + `first_name`
  + `last_name`
  + `middle_name`
  + `name`
  + `name_format`
  + `picture`
  + `short_name`As a result, the following fields that belonged to public\_profile are deprecated:
  + `age_range`
  + `context`
  + `cover`
  + `currency`
  + `devices`
  + `gender`
  + `link`
  + `locale`
  + `timezone`
  + `updated_time`
  + `verified`
* The [`rsvp_event`](/docs/facebook-login/permissions/#reference-rsvp_event) and [`user_managed_groups`](docs/facebook-login/permissions/#reference-user_managed_groups) permissions are deprecated. The [`user_managed_groups`](docs/facebook-login/permissions/#reference-user_managed_groups) permission can still be used for testing purposes but cannot be submitted for [Login Review](/docs/facebook-login/review).

* Five new permissions have been added:
  + [`groups_access_member_info`](/docs/facebook-login/permissions/#reference-groups_access_member_info) – for receiving member-related data on group content.
  + [`publish_to_groups`](/docs/facebook-login/permissions/#reference-publish_to_groups) – for posting content into a group on behalf of a user.
  + [`user_age_range`](https://developers.facebook.com/docs/facebook-login/permissions#reference-user_age_range) – for accessing a person's age range.
  + [`user_gender`](#) – for accessing a person's gender.
  + [`user_link`](#) – for accessing the Facebook profile URL for another user of the app.

#### Reading Edges and Fields

* The following edges and fields, when read with a [User](/docs/facebook-login/access-tokens) access token, return only the current user and only if applicable.

  Node | Edges | Fields || [`Album`](/docs/graph-api/reference/album/) |  | `from` |
  | [`Photo`](/docs/graph-api/reference/photo/) | `/likes`  `/reactions`  `/tags` | `/tags/tagging_user`  `target` |
  | [`Post`](/docs/graph-api/reference/photo/) | `/likes`  `/reactions` | `message_tags`  `story`  `to`  `with_tags` |
  | [`Video`](/docs/graph-api/reference/video/) | `/likes`  `/reactions`  `/tags` |  |

---

### Deprecations

There are no deprecations for this version.

---

### 90-Day Breaking Changes

* [All Apps](#apps)
* [Instagram Graph API](#instagram)
* [Page Insights](#gapi-90-page-insights)
* [Places Graph](#places-graph)
* [User Node](#user-node)

#### All Apps

* **Development Mode** — Apps in development mode are now rate-limited to 200 calls per hour, per page-app pair, and can only access Users who have a role on the app (admin, developer, or tester).
* **Public Mode** — Apps in public mode no longer allow their admins, developers, or testers to access permissions or features that normally require app review. This affects all apps built after May 1st, 2018, immediately. Apps built before then will not be affected until August 1st, 2018.

#### Instagram Graph API

* **Business Verification** — All apps must undergo [Business Verification](/docs/apps/review), which is part of the App Review process and now required for all Instagram Graph API endpoints. Apps previously reviewed before May 1st, 2018, have to be reviewed again, and have until August 1st, 2018 to do so, or lose access to the API.

#### Page Insights

* Only non-zero values will be returned for [Page Insights breakdown metrics](https://developers.facebook.com/docs/graph-api/reference/v3.0/insights).
* Page and Post Story engagement metrics, including `metric` used with the metric field, renamed from `stories` to `activity`.
* Page Post Consumptions engagement metrics, including `metric` used with the metric field, renamed from `post_consumption*` to `post_clicks*`.

* **`GET /{page-id}/insights/{metric}`** - The following metrics will be removed in 90 days:

  + `page_story_adds`
  + `page_story_adds_by_age_gender_unique`
  + `page_story_adds_by_city_unique`
  + `page_story_adds_by_country_unique`
  + `page_views`
  + `page_views_unique`
  + `page_views_login`
  + `page_views_login_unique`

* **`GET /{post-id}/insights/{metric}`** - The following metrics will be removed in 90 days:

  + `post_story_adds_by_action_type`
  + `post_story_adds_by_action_type_unique`
  + `post_story_adds_unique`
  + `post_story_adds`
  + `post_fan_reach`
  + `post_interests_impressions`
  + `post_interests_impressions_unique`
  + `post_interests_consumptions`
  + `post_interests_consumptions_unique`
  + `post_interests_consumptions_by_type`
  + `post_interests_consumptions_by_type_unique`
  + `post_interests_action_by_type`
  + `post_interests_action_by_type_unique`

#### Places Graph

* **New Place ID type** — Places Graph endpoints now return a new type of Place ID. Please refer to the [Places Graph documentation](/docs/places) to learn more. Older versions of the API will continue returning the old type of IDs until August 1st, 2018.
* `/photos` **edge** — The `type` parameter for the `/photos` edge (which is available on several nodes), no longer supports `uploaded` as a value for `GET` operations (`GET /object/photos?type=uploaded`).

#### User Node

* `GET /user` — The `third_party_id` field is deprecated. Apps using older versions of the API can get this field until July 30th, 2018. Apps installed by the User on or after May 1st, 2018, cannot get this field, no matter which version of the API they are using.

## Marketing API

**Released** May 1, 2018 | **Available Until** February 1, 2019 | [Blog Post](https://developers.facebook.com/ads/blog/post/2018/05/01/marketing-api-v30/)

* [New Features](#mapi-new)
* [Breaking Changes](#mapi-break)
* [Deprecations](#mapi-deprecate)
* [Immediate Deprecations](#imm-deprecate)

---

### New Features

#### Lowest-Cost Bid Strategy, `bid_strategy` Field

We introduced the new field `bid_strategy` for `{account-id}/adsets` which enables you to select an ads bidding strategy based on your business goals. Each strategy has advantages and tradeoffs. Options include:

* `LOWEST_COST` - Get the most results based on your ad set budget and delivery `optimization_goal`. Facebook will automatically bid more as needed to spend your budget. You can provide a maximum for your bid or provide no limit with this option.
* `TARGET_COST` - Provides stable average costs for your ads as you increase your ad set budget.

For more information, see [Ads Buying and Optimization, Bid Strategy](/docs/marketing-api/bidding-and-optimization#auto)

---

#### Collection Ads, Creating

**New API for Creating Collection Ads** - In the past, Facebook created a canvas in the background each time you created a collection ad. This limited your access to the underlying canvas; you could not use it to retarget audiences with canvas engagement audiences. Now when you create a collection ad from product sets, you **must also explicitly create a canvas with the correct elements**. When you use this canvas in a collection ad, Facebook automatically generates the collection ad. For more details, see [Collection Ads from Product Sets](/docs/marketing-api/guides/collection#product).

---

### Breaking Changes

#### Ads Management

* **Right-hand Column Invalidation** - We invalidate ads that only target the Facebook position, `right_hand_column` with invalid objectives for `right_hand_column` on `{ad_account_id}/adsets`. We now only support right-hand-side placement for supported ad formats with these objectives: Traffic, Conversions, and Product Catalog Sales.
* `is_autobid` and `is_average_price_pacing` is deprecated in both `GET` and `POST` in v3.0 and later.

#### Audiences and Ads Targeting

* **Changed Rules Syntax for Custom Audiences** - We updated the structure for rules used for creating website custom audiences, mobile app custom audiences, page engagement custom audiences, lead ads engagement audiences, canvas engagement audiences and offline custom audiences. This enables you to create rules based on aggregate behavior, rules from different event sources and to exclude rules. See:

  + [Custom Audiences from Your Website, Audience Rules](/docs/marketing-api/audiences-api/mobile-apps),
  + [Custom Audiences from your Mobile App, Audience Rules](/docs/marketing-api/audiences-api/mobile-apps#rules),
  + [Page Engagement Custom Audiences](/docs/marketing-api/audiences-api/engagement),
  + [Engagement Audiences for Lead Ads](/docs/marketing-api/guides/lead-ads/engagement-audiences),
  + [Engagement Audiences for Canvas](/docs/marketing-api/guides/canvas-ads#audience) and
  + [Custom Audiences from Offline Conversions](/docs/marketing-api/audiences-api/offline).

#### Dynamic Ads

* **Product Catalog Access** - To access catalog items you must specify the correct catalog vertical. If your request does not match the correct vertical for your catalog, you will get an error. For example, if you have an ecommerce catalog you should access it with the corresponding `/products` endpoint such as `GET {catalog_id}/products`, `GET {product_feed_id}/products`, or `GET {product_set_id}/products`. You cannot access the catalog with endpoints for other verticals such as `GET {catalog_id}/autos`, `GET {product_feed_id}/hotels`, or `GET {product_set_id}/flights`.
* **Empty String in Template Tags** - We no longer allow empty strings as parameters for Dynamic Ads, template tag options. For example, if you pass an empty string to `{{trip.checkin_date date_format:}}` you get an error. For background information, see [Dynamic Ads, Ads Management](/docs/marketing-api/dynamic-product-ads/ads-management#adtemplate).

#### Ads Insights and Measurement

* **Insight Timeouts** - If we expect an Insights API request results in a timeout before completion, we return an error with error code `100` and subcode `1504033`. We estimate this based on request size and processing progress made relative to the timeout limits. If you get this error, you should make an asynchronous Insights API request for this data. See [Insights API Asynchronous Jobs](/docs/marketing-api/insights/best-practices#asynchronous).
* **Negative Values in Event Data** - If you post event data to `{data_set_id}/events` with a negative value, it fails. This impacts the `data` field for `POST /{data_set_id-id}/events`.

* **Insights on Campaign Budget Optimization** - `adset_budget_value` now returns `using campaign budget` when your ad campaign uses campaign budget optimization. This impacts:

  + `GET {adaccount-id}/insights`,
  + `GET {campaign-id}/insights`,
  + `GET {adset-id}/insights`,
  + `GET {ad-id}/insights`,
  + `POST {adaccount-id}/insights`,
  + `POST {campaign-id}/insights`,
  + `POST {adset-id}/insights`,
  + `POST {ad-id}/insights`.

* **Default Sorting for Pixel** - If you call the `GET {account_id}/adspixel` edge on either a business account or ad account we return results, sorted by default, by pixel name instead of last pixel fire time.
* **Rename pixel stats field** - We renamed the `timestamp` field on the pixel stats edge to `start_time`. This represents the start time when we begin aggregating hourly data on pixel fires. We now return this in [ISO 8601 format](https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.iso.org%2Fiso-8601-date-and-time-format.html&h=AUAsfOUXD1Lg3KQtHvv8FTLzzz-tZ2tpqzIL33ATq3SsN8k5khIFAaJpySvfrL_RTOSKCB7se3LsgUn68EcX4p7_m0b6bZub20OOU-YL1eDITQP75OT2qiMbhJWO0mwpzLclMP4kPChY4Zk-) and include the timezone offset. This fixes an issue where we returned invalid Unix timestamps. The following endpoints will be affected: `GET {ads-pixel-id}/stats`.

### Deprecations

#### Business Manager

Deprecated `POST {pixel-id}/shared_agencies` endpoint. Please use Business Manager UI for sharing ads pixel with agencies.

#### Ads Management

* Deprecated `kpi_custom_conversion_id`, `kpi_type`, and `kpi_results` from [`/{ad_campaign_id}`](/docs/marketing-api/reference/ad-campaign-group) and [`/ad_account_ID/campaigns`](/docs/marketing-api/reference/ad-account/campaigns).

* Deprecated the `redownload` flag from the following endpoints to simplify the API:
  + `POST {ad-id}/`,
  + `POST {adset-id}/`,
  + `POST act_{ad-account-id}`,
  + `POST act_{ad-account-id}/ads`,
  + `POST act_{ad-account-id}/adsets`You can still read this information with the `fields` parameter.

* Deprecated the field `zipbytes` from `POST act_{ad-account-id}/adimages` and removed the ability to upload ZIP files at that edge. Please use an image with the extensions: `jpg`, `jpeg`, `gif`, `bmp`, `png`, `tiff`, or `tif`.
* Deprecated the current method to create collection ads which used one API call with all required assets as parameters. Instead you now need to create a canvas first and then use the canvas link to create collection ad. This enables you to access to underlying canvas object so you can, for example, retarget audiences. See [Collection Ads](/docs/marketing-api/guides/collection).
* Deprecated use of the Carousel ad format for ads with the Page Post Engagement objective. This combination is no longer valid. See [Validation, Objectives and Creatives](/docs/marketing-api/validation#objective_creative).

#### Ads Buying and Bidding

* Deprecated the fields `is_autobid` and `is_average_price_pacing` from endpoints: `POST {ad-account-id}/adsets` and `POST {adset-id}`. Instead use the new `bid_strategy` field to specify a particular bid strategy for the ad set. For more information, see [Bidding and Optimization](/docs/marketing-api/bidding-and-optimization).

* Deprecated fields under `delivery_estimate` for ads and ad accounts. The results did not meet advertiser needs. Moreover, many advertisers have business goals that may not be best fulfilled by Facebook's suggested bid amount. Deprecated fields and parameters include:

  + `bid_estimate` field,
  + `currency` parameter,
  + `daily_budget` parameter,
  + `optimize_for` parameter

  We recommend you use the true, instrinsic business value you get from Facebook ads and bid based on this. If you do not yet know this value, we suggest you use auto-bid. For background see [Ads Help Center, Ad Auctions](https://www.facebook.com/business/help/430291176997542) and [Ads Buying and Optimization](/docs/marketing-api/bidding-and-optimization).

* Deprecated returned result from `curve_budget_reach` field on `GET /{rf-prediction-id}`. We now return map, and deprecated the JSON serialized string return value. This impacts: `GET /{rf-prediction-id}`.
* Deprecated the edge `GET /{ad-account-id}/ratecard`.

* Deprecated several fields related to billing on `/ad_accounts`. This includes:

  + `next_bill_date`
  + `active_billing_date_preference`
  + `pending_billing_date_preference`
  + `active_asl_schedule`
  + `salesforce_invoice_group_id`
  + `transactions`
  + `adspaymentcycle`
  + `show_checkout_experience`

* Deprecated `pixel_id` and `external_event_source` fields `GET /customaudience`.

#### Ads Insights and Measurement

* Deprecated `matched_unique_users` on `OFFLINE_EVENT_SET_ID` returned by `GET /{data-set-id}` and `GET /{data-set-upload-id}`. See [Offline Conversions API](/docs/marketing-api/offline-conversions).
* Deprecated the `attributed_events` edge and `attribute_stats` field on the `GET /{data_set_id} API`. Use the `GET /{data_set_id}/stats` API to get attributed event stats.
* Deprecated the field `matched_unique_users` on `OFFLINE_EVENT_SET_ID` returned by `GET /{data-set-id}` and GET `/{data-set-upload-id}`.
* Deprecated default return values at `GET {data_set_upload_id}`. This no longer return these fields by default: `first_upload_time`, `last_upload_time`, `api_calls`, `valid_entries`, `matched_entries`, `duplicate_entries`, `event_time_min`, `event_time_max`, `event_stats`, and `matched_unique_users`.
* Deprecated default return values at `GET {data_set_id}/stats`. This now only return count stats by default. To specify which stats should be returned use the `fields` parameter or `summary` parameter for cumulative stats such as `average_upload_delay`.
* Deprecated default return values for `GET {data_set_id}`. This no longer returns these fields by default: `attribute_stats`, `duplicate_entries`, `event_stats`, `event_time_max`, `event_time_min`, `matched_entries`, `matched_unique_users`, `usage`, `valid_entries`.
* Deprecated the `GET {data-set-upload-id}/stats` edge. Please use `valid_entries` or `matched_entries` fields from `GET {data-set-upload-id}` instead.
* Deprecated `canvas_component_avg_pct_view` from the Insights API.
