## Version 2.8

[Graph API](#gapi-v2-8) | [Marketing API](#mapi-v2-8)

Changelog entries are categorized in the following way:

* **New Features** — New products or services, including new nodes, edges, and fields.
* **Changes** — Changes to existing products or services (not including **Deprecations**).
* **Deprecations** — Existing products or services that are being removed.
* **90-Day Breaking Changes** — Changes and deprecations that will take effect 90 days after the version release date.

**New Features**, **Changes**, and **Deprecations** only affect this version. **90-Day Breaking Changes** affect all versions.

[Breaking Changes](/docs/graph-api/changelog/breaking-changes) are not included here since they are not tied to specific releases.

---

### Graph API v2.8

**Released** October 5, 2016 | **Available until** April 18, 2019

* [New Features](#gapi-new-v2-8)
* [Changes](#gapi-change-v2-8)
* [Deprecations](#gapi-deprecate-v2-8)
* [90-Day Breaking Changes](#gapi-90-v2-8)

---

### New Features v2.8

* [Open Graph](#gapi-new-open-graph-v2-8)
* [Resumable Upload API](#gapi-new-resumable-v2-8)
* [ThreatExchange](#gapi-new-threat-v2-8)

#### Open Graph Actions

* Two new common Open Graph action types, available to all developers in all versions of the API, have been added:

  + `books.rates`
  + `games.plays`

#### Resumable Upload API

* Upload files a small piece at a time, allowing for more reliability over poor connections. Please see our guide on [the Resumable Upload API](/docs/graph-api/resumable-upload-api) for more information. This API is only available for page thumbnails right now, but will expand to other types of media in the future (like video).

#### ThreatExchange

* ThreatExchange has some new features, including support for Webhooks and new tagging functionality. Please see the [ThreatExchange Changelog](/docs/threat-exchange/reference/changelog) for more information.

---

### Changes v2.8

* [Pages](#gapi-change-pages-v2-8)

#### Pages

* **Feed Targeting** - The `targeting` and `feed_targeting` fields on the [`/page/feed`](/docs/graph-api/reference/page/feed) edge now consistently use `geo_locations` instead of specifying geography via other methods. See our [guide on targeting](/docs/graph-api/reference/targeting) which includes information about the `geo_locations` object.

---

### Deprecations v2.8

* [Open Graph](#gapi-deprecate-opengraph-v2-8)
* [User](#gapi-deprecate-user-v2-8)

#### Open Graph

* **Custom Open Graph Actions** - Apps can no longer create new Open Graph action or object types or publish Open Graph Stories that use custom action or object types. Approximately 1 year after the v2.8 release, no version of the API will allow publishing stories that use custom action or object types. Please see our [deprecation guide](https://developers.facebook.com/docs/sharing/opengraph/custom-open-graph-deprecation) for more information.
* **Open Graph Stories** - Localization is no longer supported.

#### User

* **`/admined_groups`** - This edge on the [User](https://developers.facebook.com/docs/graph-api/reference/user/) node has been deprecated. Use `groups` edge on the [User](https://developers.facebook.com/docs/graph-api/reference/user/) node instead.
* **`bio`** - This field on the [User](https://developers.facebook.com/docs/graph-api/reference/user/) node has been deprecated. Use the `about` field instead.

---

### 90-Day Breaking Changes v2.8

* [Open Graph](#gapi-90-opengraph-v2-8)

#### Open Graph

* **Custom Open Graph Actions**

  + No versions of the API will allow the creation of new Open Graph action or object types.
  + All App Collections will be removed from people's profiles.
  + Please see our [deprecation guide](https://developers.facebook.com/docs/sharing/opengraph/custom-open-graph-deprecation) for more information.

### Marketing API v2.8

**Released** October 5, 2016 | **Available until** July 26, 2017

* [New Features](#mapi-new)
* [Changes](#mapi-change)
* [Deprecations](#mapi-deprecate)
* [90-Day Breaking Changes](#mapi-90)

---

### New Features V2.8

* [Instant Articles](#mapi-new-instant-v2-8)
* [Facebook Offers](#mapi-new-offers-v2-8)

#### Instant Articles

* There is now a separate ads placement, so that advertisers can enable or disable showing ads in Instant Articles. This new placement options is under `/ACCOUNT_ID/adsets` and `/AD_SET_ID`. See [Targeting Specs](/docs/marketing-api/targeting-specs). If you use this placement you must also select `feed` as a position and for `device_platforms` select `mobile` since Instant Articles is for mobile only.

#### Facebook Offers

* Redesigned and easier for people to save and redeem your offer from any device. If they don't use your offer, they'll get notifications about it before it expires. To use the API to create offers:
  + Use `/nativeoffers` as an endpoint. The endpoint `/offers` is associated with the old product and has been deprecated.
  + Use `offer_id` in the `promoted_object` for an ad set.
  + To learn more see [Offer Ads](/docs/marketing-api/guides/native-offer/v2.7) and [Language Reference, Page Native Offers](/docs/graph-api/reference/page/nativeoffers/).

---

### Changes V2.8

* [Ads Management](#mapi-change-ads-manage-v2-8)
* [Ads Insight](#mapi-change-ads-insight-v2-8)
* [Business Manager](#mapi-change-biz-manager-v2-8)

#### Ads Management

* As of 2.8, Website Custom Audiences now only allow at most 200 comparisons in the rule. The number of comparisons are the number of comparison operators in the rule.

The following rule contains 3 comparisons:

```
{
  "or": [
    {
      "url": {
        "i_contains": "shoes"
      }
    },
    {
      "and": [
        {
          "event": {
            "eq":"ViewContent"
          }
        },
        {
          "price": {
            "gte": 100
          }
        }
      ]
    }
  ]
}
```

* The `place_page_set_id` field under Ad creative is now optional for versions v2.7 and v2.6 and has been deprecated in v2.8. See [Ad Creative](/docs/marketing-api/reference/ad-creative).
* `offer_data` under `link_data` for an ad object has been deprecated.
* The ad account group endpoints `AdAccountGroup` have been deprecated. To manage Ad Accounts, you should use [Business Manager](https://business.facebook.com/)Business Manager] or Business Manager API with `business_management` extended permission, see [Business Manager API, Overview](/docs/marketing-api/businessmanager).
* The edge `AD_ACCOUNT/audiences` has been deprecated.
* The `ad_object_by_url` field for `/search` in (/docs/marketing-api/targeting-search/v2.7)[Ad Targeting Search] has been deprecated.
* The fields `actor_image_hash`, `actor_image_url`, `place_page_set_id` and `actor_name` have been deprecated from ad creative `GET`.

#### Ads Insights

* We deprecated the redundant fields and parameters in `/insights` endpoint `POST` requests.
  - In earlier releases it supported the params: `fields`,`summary`, `default_summary`, `filtering` and `sort`. However `/insights` should always exactly return what you queried in the `POST` requests. In earlier releases we will display all valid fields for `/insights` if you provided an invalid field as a parameter. We now send an the error message which points to a list of valid fields.
* In the past we inconsistently returned `/insights` fields in a variety of types: some fields were `string` such as `impressions`, some were `numericstring`, and some were `floats`. We now return all numeric fields, including floats as `numericstring`. All floating point numbers will maintain six precision points.
* The insights metric `post_like` in the `actions` field is now named `post_reaction`, see [Ads Action Stats, Reference](/docs/marketing-api/reference/ads-action-stats/). This is more consistent with naming in user interfaces.

#### Business Manager

* The `owner_business` field has been deprecated and no longer exists for objects connected to a business, including [Ad accounts](/docs/marketing-api/reference/ad-campaign), [Ad Campaign](/docs/marketing-api/reference/ad-campaign), [Product Catalog](/docs/marketing-api/reference/product-catalog), and [Instagram User](/docs/graph-api/reference/instagram-user/).

---

### Deprecations V2.8

There are no deprecation.

---

### 90-Day Breaking Changes V2.8

There are no 90 Day Breaking Changes.
