# Version 9.0

## Graph API

**Released** November 10, 2020 | **Available until** February 23, 2023 | [Blog post](/blog/post/2020/11/10/introducing-graph-v9-marketing-api-v9/)

---

### Groups

#### Deprecated endpoints

*Deprecated in v9.0+. Will be deprecated in all versions February 9, 2021.*

* [`GET /{group-id}?fields=owner`](/docs/graph-api/reference/group#read)

---

### Instagram

#### Ads

*Applies to v9.0+*

[IG Media](/docs/instagram-api/reference/ig-media) IDs and [IG User](/docs/instagram-api/reference/ig-user) IDs can now be used with the Instagram Ads API to create ads. See the [Instagram Ads API](#instagram-ads-api) changelog entry for more information.

#### Insights

*Applies to v9.0+. Will apply to all versions on May 9, 2021.*

IG User [`follower_count`](/docs/instagram-api/reference/ig-user/insights#metrics-and-periods) values now align more closely with their corresponding values displayed in the Instagram app. In addition, [`follower_count`](/docs/instagram-api/reference/ig-user/insights#metrics-and-periods) now returns a maximum of 30 days of data instead of 2 years.

## Marketing API

**Released** November 10, 2020 | **Available until** August 25, 2021 | [Blog post](/blog/post/2020/11/10/introducing-graph-v9-marketing-api-v9/)

---

### Asset Customization Rules

#### Deprecated Endpoints

*Deprecated in v9.0+*.

* `GET /{asset_customization_rule_id}/`

Note: You can still query individual [asset customization rules](/docs/marketing-api/asset-customization-rules) via the [`asset_feed_spec`](/docs/marketing-api/reference/ad-asset-feed-spec/) field on the [ad creative node](/docs/marketing-api/reference/ad-creative).

---

### Bidding

#### Deprecated Bid Strategy

*Applies to v9.0+*

The `target_cost` [bid strategy](/docs/marketing-api/bidding) has been deprecated. Starting with v9.0, you can no longer create or update ad sets or ad campaigns with this setting. Instead, we recommend using [cost cap bidding](/docs/marketing-api/bidding/overview/bid-strategy#cap).

#### Deprecated Billing and Optimization Option

*Applies to v9.0+*

Starting with v9.0, CPA billing for app ads is deprecated, you cannot set both billing event and optimization goal to `APP_INSTALLS`. Instead, we recommend using the `impression` billing events.

You can still specify `APP_INSTALLS` under `billing_event` or `optimization_goal`, but not both at the same time.

---

### Business

#### Endpoint Access Restrictions

*Applies to all versions.*

Access to the following endpoints is temporarily limited to apps that have queried them within the last 90 days:

* [`POST /<APP_SCOPED_SYSTEM_USER_ID>/access_tokens`](/docs/marketing-api/system-users/install-apps-and-generate-tokens#generate-token)
* [`POST /{business-id}/business_users`](/docs/marketing-api/reference/business/business_users/)
* [`POST /{business-id}/system_users`](/docs/marketing-api/reference/business/system_users/)

---

### Catalog API

#### Product Sets

*Applies to v9.0+. Will apply to all versions February 9, 2021.*

By default, the [`DELETE /{product_set_id}`](/docs/marketing-api/reference/product-set#Deleting) endpoint can no longer delete [product sets](/docs/marketing-api/reference/product-set) while they are being used in active ads, shop collections or other usages. To override this behavior, include the new `allow_live_product_set_deletion=true` parameter in the request.

---

### Instagram Ads API

*Applies to v9.0+*

Starting with v9.0, you can use the Marketing API to create Instagram ads from existing Instagram posts. See [Use Posts as Instagram Ads, Instagram Posts](/docs/instagram/ads-api/guides/use-posts-as-ads). As part of this change, we have updated the following endpoints and fields, as described below.

These endpoints can now return Instagram User ID ([IG User](/docs/instagram-api/reference/ig-user/)), if available:

* [`GET /<ad_account_id>/connected_instagram_accounts`](/docs/marketing-api/reference/ad-account/connected_instagram_accounts/)
* [`GET /<business_id>/instagram_business_accounts`](/docs/marketing-api/reference/business/instagram_business_accounts/)
* [`GET /<ad_creative_id>`](/docs/marketing-api/reference/ad-creative)

These endpoints now accept Instagram Media ID ([IG Media](/docs/instagram-api/reference/ig-media)) and Instagram User ID ([IG User](/docs/instagram-api/reference/ig-user/)) as a parameter:

* [`POST /<ad_account_id>/adscreatives`](/docs/marketing-api/reference/ad-account/adcreatives/)
* [`POST /<ad_account_id>/ads`](/docs/marketing-api/reference/ad-account/ads/)

This endpoint now accepts Instagram Media ID ([IG Media](/docs/instagram-api/reference/ig-media)) as a parameter:

* [`POST /<ad_account_id>/advideos`](/docs/marketing-api/reference/ad-account/advideos/)

This field can now return an Instagram User ID ([IG User](/docs/instagram-api/reference/ig-user/)), if available:

* [`GET /<page-id>?fields=connected_page_backed_instagram_account`](/docs/graph-api/reference/page)

---

### Lead Ads

#### Lead Retrieval for Dev Mode Apps

*Applies to v9.0+. Will apply to all versions February 9, 2021.*

Starting in v9.0, you will not be able to [retrieve leads](/docs/marketing-api/guides/lead-ads) if your app is in [Dev Mode](/docs/apps#development-mode). For testing purposes, Dev Mode app users can access leads submitted by someone with a role in that same app. See [App Roles](/docs/apps#roles). Apps in Live Mode continue to have access to all leads.

The rules are different for [business apps](/docs/development/create-an-app/app-dashboard/app-types#business), since they do not have Dev and Live modes. If you are running a [business app](/docs/development/create-an-app/app-dashboard/app-types#business), you must request [Advanced Access](/docs/graph-api/overview/access-levels/#advanced-access) for the `leads_retrieval` permission to be able to retrieve leads.
