# Version 10.0

## Graph API

**Released** February 23, 2021 | **Available until** June 8th, 2023 | [Blog post](https://developers.facebook.com/docs/graph-api/changelog/version10.0)

---

### Business Apps

#### Access Levels

*Applies to all apps created after February 16, 2021.*

All [Business](/docs/development/create-an-app/app-dashboard/app-types#business) type apps created after February 16, 2021 will automatically be granted [Standard](/docs/graph-api/overview/access-levels) access to the [`email`](/docs/permissions/reference/email) and [`public_profile`](/docs/permissions/reference/public_profile) permissions.

*Applies to all existing apps created after February 16, 2021.*

All Business type apps created before February 16, 2021 will automatically be granted [Advanced](https://developers.facebook.com/docs/graph-api/overview/access-levels) access to the `email` and `public_profile` permissions. Apps that are not using the `email` or `public_profile` permissions will be downgraded to Standard access for these two permissions.

Business type apps can upgrade to Advanced access for the `email` and `public_profile` permissions without going through [App Review](/docs/app-review).

---

### Groups

*Applies to v10.0+. Will apply to all versions on May 25, 2021.*

* To align with other Facebook data retention policies, the Groups API will only include data created within the last 90 days of your queries. The data returned is dependent on the access level or mode of your app and your role on the app.
* Groups API will now use a 2 tiered API access level system, [Standard level and Privileged level](https://developers.facebook.com/docs/graph-api/overview/access-levels/), instead of Dev mode and Live mode access. Standard level access will only allow you to get data for users that have a role on your app, while Privileged level access will allow you to get data from all users in the group that the app is installed in.

---

### Pages

#### Reinstated endpoint

*Applies to v10.0+. Will apply to all versions on May 25, 2021.*

The `DELETE /{page-id}/tabs` endpoint that was [deprecated in v8.0](https://developers.facebook.com/docs/graph-api/changelog/version8.0) has been reinstated in v10.0 and will be reinstated in all versions on May 25, 2021.

---

### Threat Exchange

#### Deletion of expired data

*Will apply to all versions on May 25, 2021.*

Data uploaded to ThreatExchange with a non-zero `expire_time` will be [permanently deleted](/docs/threat-exchange/reference/deleting) at the expiration time indicated. If you wish to delete data that is no longer valid, set the `expired_on` field to the current time to have the data deleted immediately.

Additionally, all non-Facebook ThreatDescriptors will be permanently deleted once they reach the expiration date set by the creator. If your application currently has expired ThreatDescriptors that you don’t want deleted, you must extend the expiration date or set it to ‘0’ to ensure that the data never expires.

---

### URL

*Applies to v10.0+. Will apply to all versions on May 25, 2021.*

#### Engagement

* Due to privacy concerns, counts returned by a [`GET /?id={url}/engagement`](/docs/graph-api/reference/url/#read) request may not match raw counts.
* Requests for the [`GET /?id={url}/engagement`](/docs/graph-api/reference/url/#read) field for the same URL will be limited to 10 requests per hour.

## Marketing API

**Released** February 23, 2021 | **Available until** October 4, 2021 | [Blog post](/blog/post/2021/02/23/introducing-graph-v10-marketing-api-v10/)

---

### Ad Account

#### Field changes

*Applies to v10.0+. Will apply to all versions May 25, 2021.*

The `agency_client_declaration` field on the [AdAccount](https://developers.facebook.com/docs/marketing-api/reference/ad-account/) node now requires [Admin privileges](https://www.facebook.com/business/help/442345745885606?id=180505742745347) for all operations.

---

### Ads Insights API

#### Updated date\_preset parameter

*Applies to v10.0+.*

* The [`lifetime`](/docs/marketing-api/insights/parameters/) parameter (`date_preset=lifetime`) is disabled and replaced with `date_preset=maximum`, which can be used to retrieve a maximum of 37 months of data. The API will return an error when requests contain date ranges beyond the 37-month window.
* For v9.0 and lower, there will be no change in functionality until May 25, 2021. At that time, `date_preset=maximum` will be enabled and any `lifetime` calls will default to `maximum` and return only 37 months of data.

---

### Business

#### Easing of Previous Endpoint Access Restrictions

*Applies to 10+.*

In v9.0, access to the endpoints below was [restricted](/docs/graph-api/changelog/version9.0#business). Access has been restored to all apps, but apps can now only target businesses (or child businesses of those businesses) that have claimed them:

* [`POST /<APP_SCOPED_SYSTEM_USER_ID>/access_tokens`](/docs/marketing-api/system-users/install-apps-and-generate-tokens#generate-token)
* [`POST /{business-id}/business_users`](/docs/marketing-api/reference/business/business_users/)
* [`POST /{business-id}/system_users`](/docs/marketing-api/reference/business/system_users/)

---

### Targeting

#### Connections Targeting

*Will apply to all versions May 24, 2021.*

The following endpoints will no longer accept [connections targeting](/docs/marketing-api/audiences/reference/advanced-targeting#facebook_connections) when creating or editing ad campaigns:

* [`POST /<ad_account_id>/adsets`](/docs/marketing-api/reference/ad-account/adsets/)
* [`POST /<adset_id>`](/docs/marketing-api/reference/ad-campaign/)

This change will not affect any existing running campaigns.

#### Lookalike Audiences

**UPDATED APRIL 28, 2021:** The removal of the`location_spec` and `country` parameters from lookalike audience creation is currently delayed. Updates on when this change will go into effect will be forthcoming.

The `location_spec` and `country` parameters will be removed from lookalike audience creation. The location for the lookalikes will be defined by the country location in the campaign’s targeting specification.

There will be no impact on existing campaigns given this change. This requirement will only impact new and edited campaigns.

The following endpoints and fields will be affected:

* `POST /<ad_account_id>/customaudiences`
* `POST /<ad_account_id>/adsets`
* `POST /<ad_account_id>/adaccounts?adaccounts=<SHARED_TO_AD_ACCOUNT_ID>`
* `GET /<ad_account_id>/reachestimate`
* `GET /<ad_account_id>/delivery_estimate`
* `GET /<ad_account_id>?fields=approximate_count`
* `GET /<ad_account_id>?fields=delivery_status`
* `GET /<ad_account_id>?fields=operation_status`

See [Lookalike Audiences: Upcoming Lookalike Changes](/docs/marketing-api/audiences/guides/lookalike-audiences#changes) for more information on these updates.
