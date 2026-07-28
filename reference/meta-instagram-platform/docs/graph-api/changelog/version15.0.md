# Version 15.0

## Graph API

**Released** September 15, 2022 | **Available until** November 20, 2024 | [Blog post](/blog/post/2022/09/15/introducing-facebook-graph-api-v15-and-marketing-api-v15/)

### Instagram Graph API

#### Story Webhooks

*Applies to all versions.*

[Story insights webhooks](/docs/graph-api/webhooks/reference/instagram/#story_insights) notifications are now sent 1 hour after story expiration.

### Pages API

#### Custom Page Tabs

*Applies to v15.0+. Will apply to all versions December 14, 2022.*

Custom Page Tabs are no longer available. The following endpoints are affected:

* [`POST /{page-id}/tabs`](/docs/graph-api/reference/page/tabs/#Creating)
* [`DELETE /{page-id}/tabs`](/docs/graph-api/reference/page/tabs/#Deleting)

## Marketing API

The expiration date for Marketing API v14.0 and v15.0 has been moved to September 20, 2023 from August 15, 2023 to provide more time for the platform integrating changes for [DSA enforcement](https://www.facebook.com/business/help/605021638170961). Note v14.0 and v15.0 will expire on the same day. To avoid disruption to your apps, we recommend upgrading to our latest version before September 20.

**Released** September 15, 2022 | **Available until** September 20, 2023 | [Blog post](/blog/post/2022/09/15/introducing-facebook-graph-api-v15-and-marketing-api-v15/)

### Audiences

#### Special Ad Audiences

*Applies to all versions.*

[Special Ad Audiences](/docs/marketing-api/audiences/special-ad-category#special-ad-audiences), which are similar to lookalike audiences for housing, employment, and credit advertisers, have been deprecated due to a settlement with the US Department of Housing and Urban Development. See the [developer blog](https://developers.facebook.com/blog/post/2022/08/15/updating-special-ad-audiences-for-housing-employment-and-credit-advertisers/) for more information about this announcement.

You can no longer create Special Ad Audiences. Special Ad Audiences endpoints will be removed no later than December 31, 2022.

The following endpoints and fields are affected:

* [`GET /{ad-account-id}/customaudiences?fields=operation_status`](/docs/marketing-api/reference/ad-account/customaudiences/#Creating)
* [`POST /{ad-account-id}/adsets?fields=subtype`](/docs/marketing-api/reference/ad-account/adsets#Creating)
* [`POST /{ad-account-id}/customaudiences?fields=subtype`](/docs/marketing-api/reference/ad-account/customaudiences/#Creating)
* [`POST /{ad-campaign-id}?fields=subtype`](/docs/marketing-api/reference/ad-campaign-group#Creating)
* [`POST /{custom-audience-id}`](/docs/marketing-api/reference/custom-audience#Creating)


#### Advantage Custom Audiences

*Applies to v15.0+. Will apply to all versions on December 14, 2022.*

When creating an ad set with any objective and with a non-data file custom audience in inclusion, Advantage custom audiences will be turned on by default.

When creating an ad set with a non-Advantage lookalike objective (that is, Value Optimization, Offsite Conversion, App Installs and Messages) with `lookalike` in inclusion, Advantage lookalike will be turned on by default.

Advantage custom audience and Advantage lookalike can be enabled or disabled through the `targeting_relaxation_types` targeting spec parameter. `targeting_relaxation_types` accepts either `custom_audience` and `lookalike` as a key, and if a value of `0` is passed, it will be disabled. If a value of `1` is passed, it will be enabled. If no key/value pair is passed, it will be considered as enabled.

The following endpoints and fields are affected:

* [`GET /{ad-account-id}/adsets`](/docs/marketing-api/reference/ad-account/adsets#Reading)
* [`POST /{ad-account-id}/adsets`](/docs/marketing-api/reference/ad-account/adsets#Creating)
* [`GET /{ad-set-id}?fields=targeting`](/docs/marketing-api/reference/ad-campaign#Reading)


#### Advantage Detailed Targeting

*Applies to v15.0+. Will apply to all versions on December 14, 2022.*

When creating an ad set with the Messages or App Installs optimization goals, [Advantage lookalike](https://www.facebook.com/business/help/1212225059146059) and/or [Advantage detailed targeting](https://www.facebook.com/business/help/128066880933676?id=176276233019487) will be turned on by default and cannot be disabled.

When querying ad sets with the Messages or App Installs optimization goals that have Advantage detailed targeting and/or Advantage lookalike enabled, a `targeting_optimization_types` map will be returned with the `detailed_targeting` and `lookalike` properties indicating that the expansion is enabled. When querying delivery estimates for ad sets with the Messages or App Installs optimization goals, the `targeting_optimization` field will no longer be accepted and an error will be thrown.

For existing ad sets, you will be able to pass the `targeting_optimization` field.

The following endpoints are affected:

* [`GET /{ad-account-id}/adsets`](/docs/marketing-api/reference/ad-account/adsets#Reading)
* [`POST /{ad-account-id}/adsets`](/docs/marketing-api/reference/ad-account/adsets#Creating)
* [`GET /{ad-set-id}/delivery_estimate`](/docs/marketing-api/reference/ad-campaign/delivery_estimate/#Reading)

### Campaigns

#### Deprecated optimization type

*Applies to v15.0+. Will apply to all versions on December 14, 2022.*

Beginning September 15, 2022, advertisers will no longer be allowed to create incremental conversion optimization campaigns. Existing conversion optimization campaigns will behave normally.

The following endpoint is affected:

* [`POST /{ad_account_id}/campaigns`](/docs/marketing-api/reference/ad-account/campaigns/#Creating)


#### Custom Conversions

*Applies to v15.0+.*

We now require new Custom Conversions to contain at least one rule when they are created. Otherwise, campaigns should optimize on the event directly.

The following endpoint is affected:

* [`POST /{ad_account_id}/customconversions`](/docs/marketing-api/reference/custom-conversion#Creating)
