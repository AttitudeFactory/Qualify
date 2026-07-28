# Version 2.10

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

**Released** July 18, 2017 | **Available until** November 7, 2019

* [New Features](#gapi-new)
* [Changes](#gapi-change)
* [Deprecations](#gapi-deprecate)
* [90-Day Breaking Changes](#gapi-90)

---

### New Features

* [Webhooks](#gapi-new-webhooks)

#### Webhooks

* **Webhooks for Page Events** - The following actions will now trigger an update for Page `feed` field subscriptions:

  + Auto-publishing a scheduled event
  + Commenting on the event story
  + Creating and publishing an event
  + Publishing a draft event

---

### Changes

* [Credit Allocations](#gapi-change-credit)
* [Pages](#gapi-change-pages)
* [User](#gapi-change-user)
* [Webhooks](#gapi-change-webhooks)

#### Credit Allocations

* **`GET /{extended-credit-id}`** — The following fields have been renamed:

  + `invoice_email` to `extended_credit_emails`
  + `invoice_group` to `extended_credit_invoice_groups`
  + `sequential_liability_amount` to `allocated_amount`

* **`GET /{extended-credit-id}`** — The following fields have been added:

  + `liable_biz_name fields`
  + `owner_business field` with subfields `id` and `name`
  + `owning_credit_allocation_configs`
  + `send_bill_to_biz_name`

* **`GET /{extended-credit-id}`** — The following field has been removed:

  + `business_id field`

* **`extended_credit_invoice_groups`** - The following subfields have been added:

  + `ad_accounts` with `account_id` and `name` subfields
  + `email`
  + `id`
  + `name`

* [**`CurrencyAmount`**](/docs/graph-api/reference/currency-amount) - The following fields with now return a `CurrencyAmount` object instead of just the amount:

  + `allocated_amount`
  + `balance`
  + `max_balance`
  + `online_max_balance`

#### Pages

* **[`GET /{page-id}/conversations`](/docs/graph-api/reference/v2.10/page/conversations)** — Only the following fields will now be returned:

  + `id`
  + `link`
  + `updated_time`

#### User

* **[`GET /{user-id}/conversations`](/docs/graph-api/reference/v2.10/page/conversations)** — Only the following fields will now be returned:

  + `id`
  + `link`
  + `updated_time`

#### Webhooks

* **App Restriction Enforcement** — Specifying an access token for a user who fails the application's restrictions (such as country or age) will result in an error, unless an `appsecret_proof` is specified in the request.

---

### Deprecations

* [Events](#gapi-deprecate-events)

#### Events

* **`GET /{event-id}/videos`** — This edge has been removed.

---

### 90-Day Breaking Changes

* [Comments](#gapi-90-comments)
* [Posts](#gapi-90-posts)
* [URLs](#gapi-90-urls)
* [Videos](#gapi-90-videos)

#### Comments

* **`POST` and `DELETE /{comment-id}`** — This node now requires a valid page access token.
* **`POST and DELETE /{object-id}/comments`** — This node now requires a valid page access token.
* **`GET /{object-id}/comments`** - This edge now requires a valid access token.

#### URLs

* **`POST /{url}`** - This node now requires a valid access token.
* **`GET /{url}`** - `og_object` is no longer returned by default but must be included in the fields parameter.
* **`/{url}` Scraping** - `GET` requests will no longer scrape the URL. `POST /{url}` must now be used to scrape the URL.

#### Posts

* **`/{post-id}`** - This node now requires a valid access token.

#### Videos

* **`/{video-id}`** - This node now requires a valid page access token.

## Marketing API

**Released** July 18, 2017 | **Available until** May 8, 2018

* [New Features](#mapi-new)
* [Changes](#mapi-change)
* [Deprecations](#mapi-deprecate)
* [90-Day Breaking Changes](#mapi-90)
* [Breaking Changes](#mapi-break)

---

### New Features

* No new features.

---

### Changes

* No changes.

---

### Deprecations

* No deprecations.

---

### 90-Day Breaking Changes

* No 90-day breaking changes.

---

### Breaking Changes in Marketing API v2.10

* [Ads Management](#mapi-break-ads)
* [Insights](#mapi-break-insights)
* [Signals and Targeting](#mapi-break-signals)

#### Ads Management

* **Holdout fields** - The following fields have been deprecated from `POST /{ad_account_id}/ads` and `GET /{ad_id}`:

  + `holdout_end`
  + `holdout_hash`
  + `holdout_start`
  + `no_show_offset`
  + `no_show_percentage`
  + `show_end`
  + `show_start`

* **`POST /{ad_account_id}/adcreatives`** - The following parameter is now deprecated:

  + `follow_redirect`

* `creative_rotation_parameter` and `creative_rotation` type from `GET ADSET_ID` and `POST AD_ACCOUNT_ID/adsets` are deprecated.
* Real-time bidding partner `GET` endpoints are deprecated. This includes `GET /RTB_PARTNER_ID` and `GET /RTB_PARTNER_ID/stats` endpoints. We also removed the field `rtb_flag` from `POST /ADSET_ID` and `POST /ADGROUP_ID`.

#### Signals and Targeting

* **Reach and Frequency Predictions** - As of 2.10 we now provide `target_spec` as a JSON object; you no longer have to parse the response into JSON.

#### Insights

* **Breakdowns** - The following types have been deprecated for the `action_link_click_destination` breakdown. See [Insights, Breakdowns](/docs/marketing-api/insights/breakdowns#actionsbreakdown).

  + `app_store_clicks`
  + `deeplink_clicks`
  + `website_clicks`

> Replaced by:
>
> * `click_to_app_store`
> * `click_to_app_deeplink`
> * `click_to_website`
