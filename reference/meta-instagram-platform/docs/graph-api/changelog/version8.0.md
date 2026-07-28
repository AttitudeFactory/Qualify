# Version 8.0

## Graph API

**Released** August 4, 2020 | **Available until** November 1, 2022 | [Blog post](/blog/post/2020/08/04/Introducing-graph-v8-marketing-api-v8)

---

### Access Tokens

#### Deprecated Endpoints

*Deprecated in v8.0+. Will be deprecated in all versions Nov 2, 2020.*

* [`GET /token_deprecation_check`](/docs/graph-api/reference/token-deprecation-check)

---

### Albums

#### Reinstated Endpoints

*Applies to all versions.*

* [`GET /{album-id}/likes`](docs/graph-api/reference/object/likes)

---

### App Configuration

#### App Types

*This change applies to all versions.*

Newly created apps can now choose an [App Type](/docs/apps/app-types): Business, Gaming, or None. This simplifies the App Review interface by removing inappropriate Permissions and Features based on the chosen type. In addition, apps typed as Business apps use a new authorization mechanism, no longer use modes, and have access to a new Feature. Refer to the [Business apps changelog entry](#business-apps) for details.

---

### Business Apps

Apps [typed as Business apps](#app-types) use a new authorization mechanism called [Access Levels](#access-levels). Access Levels replace the functionality provided by Development Mode and Live Mode, which have been [removed for Business apps](#mode-removal), and make the App Review process simpler and more intuitive. In addition, a [new Business Asset User Profile Access Feature](#baupa) has been released, which allows Business apps to read a small set of public User fields. These changes are described in more detail below.

#### Access Levels

*Applies to all versions.*

[Access Levels](/docs/graph-api/overview/access-levels/) are a new Graph API authorization mechanism for [Business apps](/docs/apps/app-types#business) that apply to Permissions and Features on an individual basis. Standard Access only allows access to data owned by users who have a Role on the app, or a Role in a Business that has claimed the app. Advanced Access allows access to data owned by any app user, but requires App Review. Business apps are auto-granted Standard Access for all Permissions and Features [available to their type](/docs/apps/app-types#available-permissions).

#### Development and Live Mode Removal

*Applies to all versions.*

[Development Mode](/docs/apps#development-mode) and [Live Mode](/docs/apps#live-mode) have been removed for apps typed as [Business apps](/docs/apps/app-types#business). These modes have been replaced by Access Levels, which provide the same functionality and more versatility — since Business apps have Standard Access for all available Permissions and Features, any user with a Role on the app, or a Role in a Business that has claimed the app, can grant the app any available Permission at any time. This eliminates the need for App Review or having to switch between modes during development.

#### New Business Asset User Profile Access Feature

*Applies to all versions.*

The new Business Asset User Profile Access Feature allows [Business apps](/docs/apps/app-types#business) to read a small set of public Fields on a User, as long as the User has engaged with assets owned by a Business that has claimed the app. Refer to the [Business Asset User Profile Access reference](/docs/apps/features-reference#business-asset-user-profile-access) for a list of readable User Fields.

---

### Comments

#### Reinstated Endpoints

*Applies to all versions.*

* [`GET /{comment-id}/likes`](docs/graph-api/reference/object/likes)

---

### Devices

#### Deprecated Endpoints

*Deprecated in v8.0+. Will be deprecated in all versions Nov 2, 2020.*

* [`POST /device/share`](/docs/sharing/for-devices)

---

### Groups

#### Deprecated Endpoints

*Deprecated in v8.0+.*

* `GET /{group-id}/posts`

*Deprecated in v8.0+. Will be deprecated in all versions Nov 2, 2020.*

* [`GET /{group-post-id}/likes`](/docs/graph-api/reference/object/likes)

---

### Instagram

#### New Instagram oEmbed Endpoint

*Applies to all versions.*

A new [`GET /instagram_oembed`](/docs/graph-api/reference/instagram-oembed) endpoint has been introduced. It provides the same functionality as Instagram's [Legacy oEmbed endpoints](/docs/instagram/oembed-legacy), which will be deprecated on Oct 24, 2020. The new endpoint requires an access token, so you will need a Facebook Developer account and registered app to access it. Refer to the [Instagram oEmbed document](/docs/instagram/oembed) for usage instructions and additional details.

---

### Life Events

#### Deprecated Endpoints

*Deprecated in v8.0+.*

* [`GET /{life-event-id}`](/docs/graph-api/reference/life-event)
* [`GET /{life-events-id}/photos`](/docs/graph-api/reference/life-event/photos)

---

### Links

#### Deprecated Endpoints

*Deprecated in v8.0+.*

* [`GET /{link-id}/reactions`](/docs/graph-api/reference/link)

---

### Live Videos

#### Deprecated Endpoints

*Deprecated in v8.0+.*

* [`GET /{live-video-id}/likes`](/docs/graph-api/reference/live-video/likes)

Use the [`GET /{live-video-id}/reactions` endpoint](/docs/graph-api/reference/live-video/reactions) to get likes for a LiveVideo.

#### save\_vod Parameter

*Applies to v8.0+. Will apply to all versions on Nov 2, 2020.*

The `save_vod` parameter is deprecated for the following edges:

* [`POST /{user_id}/live_videos`](/docs/graph-api/reference/user/live_videos/)
* [`POST /{group_id}/live_videos`](/docs/graph-api/reference/group/live_videos)
* [`POST /{page_id}/live_videos`](/docs/graph-api/reference/page/live_videos/)
* [`POST /{event_id}/live_videos`](/docs/graph-api/reference/event/live_videos/)

---

### Messenger Platform

#### Deprecated Endpoints

*Deprecated in v8.0+.*

* [`GET /{page-id}/thread_settings`](/docs/graph-api/reference/page/thread_settings/)
* [`POST /{page-id}/thread_settings`](/docs/graph-api/reference/page/thread_settings#Creating)
* [`DELETE /{page-id}/thread_settings`](/docs/graph-api/reference/page/thread_settings#Deleting)

#### App Review

*Applies to all versions.*

App Review for Messenger has been moved from **Products > Messenger > Settings** to **App Review** in the app dashboard. To request Messenger specific permissions, `pages_messaging`, `pages_user_gender`, `pages_user_locale`, and `pages_user_timezone`, go to **App Review > Permissions and Features**. See the [Messenger App Review documentation](/docs/messenger-platform/submission-process) for more details.

#### Messenger Profile Edge

*Applies to v8.0+.*

The nested persistant menu type has been deprecated for [`POST /{page-id}/messenger_profile`](/docs/messenger-platform/send-messages/persistent-menu).

#### New Feature: Messenger for Shops

*Applies to v8.0+.*

Support for sending and receiving products on Messenger for Shops. This includes the [Product Template](/docs/messenger-platform/send-messages/template/product/) that can be used to send products in messages, [Webhooks](/docs/messenger-platform/reference/webhook-events/messages) for messages with product template and messages from Facebook Shops Product Detail Page, and [echo Webhooks](/docs/messenger-platform/reference/webhook-events/message-echoes) for messages with products.

* [`GET /{message_id}/access_requests`](/docs/graph-api/reference/v7.0/message)
* [`POST {page_id}/message`](/docs/messenger-platform/reference/send-api/)
* [`message_echo` Webhook](/docs/messenger-platform/reference/webhook-events/message-echoes)
* [`messages` Webhook](/docs/messenger-platform/reference/webhook-events/messages)

---

### Native Offers

#### Deprecated Endpoints

*Deprecated in v8.0+.*

* [`GET /{native-offer-id}/nativeofferviews?photos`](/docs/graph-api/reference/native-offer/nativeofferviews/)

---

### Open Graph

#### Deprecated Endpoints

*Deprecated in v8.0+. Will be deprecated in all versions on Nov 2, 2020.*

* `GET /{open-graph-action-id}/comments`
* `POST /{open-graph-action-id}/comments`

---

### Pages

#### Deprecated Endpoints

*Deprecated in v8.0+.*

* [`DELETE /{page-id}/tabs`](/docs/graph-api/reference/tab/)
* `GET /{group-id}/posts`
* [`GET /{page-id}/place_topics`](/docs/graph-api/reference/page/place_topics/)
* [`GET /{page-about-story-id}`](/docs/graph-api/reference/page/page_about_story)
* [`POST /{page-about-story-id}`](/docs/graph-api/reference/page/page_about_story)
* [`POST /{page-id}/page_about_story`](/docs/graph-api/reference/page/page_about_story)

#### Page Post

*Deprecated in all versions.*

The Page Post [comment ID format](/docs/graph-api/reference/comment), `{page-id}_{post_id}_{comment-id}`, has been deprecated. Use the `{pagepost-id}_{comment-id}` format instead.

---

### Photos

#### Deprecated Endpoints

*Deprecated in all versions.*

* [`GET /{photo-id}/sharedposts`](/docs/graph-api/reference/object/sharedposts)

---

### Places

#### Deprecated Endpoints

*Deprecated in v8.0+.*

* [`GET /{place-information-id}`](/docs/graph-api/reference/v7.0/place-information) (see [Corrections](#corrections))

---

### Posts

#### Deprecated Endpoints

*Deprecated in v8.0+. Will be deprecated in all versions on Nov 2, 2020.*

* [`GET /{post-id}/likes`](/docs/graph-api/reference/post/likes/)

Use the [`GET /post/reactions` endpoint](/docs/graph-api/reference/post/reactions) to get likes for a post.

---

### Search

#### Deprecated Endpoints

*Deprecated in v8.0+. Will be deprecated in all versions Nov 2, 2020.*

* [`GET /search?type=place`](/docs/places/web/search/)
* [`GET /search?type=audience_interest`](/docs/pages/searching)

---

### Security Settings

#### Deprecated Fields

*Deprecated in v8.0+. Will be deprecated in all versions on Nov, 2020.*

* [`secure_browsing`](/docs/graph-api/reference/security-settings/#fields)

---

### Social Plugins

#### Facebook oEmbed Endpoints

*This change will apply to all versions on October 24, 2020.*

Facebook [oEmbed Endpoints](/docs/plugins/oembed-legacy), which allow apps to get embed HTML for public Facebook posts and videos, will be deprecated on October 24, 2020. Three new endpoints have been introduced which provide the same functionality as the old endpoints they are replacing:

* [`GET /oembed_page`](/docs/graph-api/reference/oembed-page/)
* [`GET /oembed_post`](/docs/graph-api/reference/oembed-post/)
* [`GET /oembed_video`](/docs/graph-api/reference/oembed-video/)

The new endpoints require an Access Token and requests will be subject to rate limiting. Please refer to the [new oEmbed endpoint documenation](/docs/plugins/oembed) for usage details and additional information.

---

### Users

#### Deprecated Endpoints

*Deprecated in v8.0+.*

* [`GET /{user-id}/taggable_friends`](/docs/graph-api/reference/user/taggable_friends)

#### Deprecated Fields

*Deprecated in v8.0+. Will be deprecated in all versions on Nov, 2020.*

* [`security_settings`](/docs/graph-api/reference/user/#fields)
* [`test_group`](/docs/graph-api/reference/user/#fields)
* [`viewer_can_send_gift`](/docs/graph-api/reference/user/#fields)
* [`is_shared_login`](/docs/graph-api/reference/user/#fields)

*Deprecated in all versions.*

* [`can_review_measurement_request`](/docs/graph-api/reference/user/#fields)
* [`is_famedeeplinkinguser`](/docs/graph-api/reference/user/#fields)

#### Reauthorization

*This change applies to all versions.*

Starting Oct 24, 2020, the following fields will require [Data Access Reauthorization](/docs/facebook-login/auth-vs-data/) after 90 days of inactivity:

* [`is_eligible_promo`](/docs/graph-api/reference/user#fields)
* [`payment_mobile_pricepoint`](/docs/graph-api/reference/user#fields)
* [`payment_pricepoints`](/docs/graph-api/reference/user#fields)

#### User Picture

*Applies to all versions on Oct 24, 2020.*

Starting October 24, 2020, the [`GET /{user-id}/picture`](/docs/graph-api/reference/user/picture) endpoint ([`GET /{user-id}?fields=picture`](/docs/graph-api/reference/user/picture)) will require an App-Scoped User ID (ASID) for tokenless requests. If you query the User with a non-ASID, you must include an [App](/docs/facebook-login/access-tokens#apptokens), [Client](/docs/facebook-login/access-tokens#clienttokens), or [User](/docs/facebook-login/access-tokens#usertokens) Access Token in the request. Refer to the [User Picture reference](/docs/graph-api/reference/user/picture) for details.

---

### Video Questions

#### Deprecated Endpoints

*Deprecated in v8.0+.*

* [`GET /{question-id}`](/docs/graph-api/reference/question)
* [`GET /{question-id}/options`](/docs/graph-api/reference/question#edges)
* [`GET /{question-id}/votes`](/docs/graph-api/reference/question_option#edges)
* [`GET /{question-option-id}`](/docs/graph-api/reference/question_option)

---

### Workplace

#### Deprecated Endpoints

*Deprecated in v8.0+. Will be deprecated in all versions on Nov 2, 2020.*

* [`GET /{company-id}/access_requests`](/docs/workplace)
* `GET /access_requests`

## Marketing API

**Released** August 4, 2020 | **Available until** May 4, 2021 | [Blog post](/blog/post/2020/08/04/Introducing-graph-v8-marketing-api-v8)

---

### Ad Accounts

#### Deprecated Endpoints

*Deprecated in v8.0+.*

* `GET /AdReportSchedule`
* [`DELETE act_{ad-account-id}/adsets`](/docs/marketing-api/reference/ad-account/adsets/)

#### Permissions

*Applies to v8.0+. Will apply to all versions on Nov 2, 2020.*

Apps need [granular permissions](/docs/facebook-login/permissions/overview#granularpermissions) to access the business fields of an Ad Account. Permissions should be granted for a specific Business object.

---

### Asset Customization Rules

#### Validation

*Applies to v8.0+.*

All ads using `asset_feed_spec` must contain at least two target customization rules. If your creative uses `asset_feed_spec` **and** includes less than two rules, you will not be able to create that ad.

This change affects [Placement Asset Customization](/docs/marketing-api/dynamic-creative/placement-asset-customization#asset-feed), [Multi-Language Ads](/docs/marketing-api/multi-language-ads), and [Segment Asset Customization](/docs/marketing-api/dynamic-creative/segment-asset-customization).

#### Segment Asset Customization

*Applies to v8.0+. Will apply to all versions on Nov 2, 2020.*

All use cases unrelated to geolocation have been deprecated for [Segment Asset Customization](/docs/marketing-api/dynamic-creative/segment-asset-customization) users. With this change, all targeting rules must contain geolocation information inside their customization spec. There is an exception for the default rule, which does not need to include geolocation.

---

### Bidding

#### Target Cost Bid Strategy

*Applies to v8.0+*

The `TARGET_COST` bid strategy is deprecated. To continue controlling cost, we recommend using [cost cap](/docs/marketing-api/bidding/overview/bid-strategy#cap) bidding. [See all available bid strategies](/docs/marketing-api/bidding/overview/bid-strategy).

---

### Business Manager

#### Deprecated Endpoints

*Deprecated in v8.0+.*

* `GET` [`{system-user-id}`](/docs/marketing-api/reference/system-user)`/updated_by`

#### Reintroduced Sharing Agreements Endpoints

*Applies to all versions*

The following endpoints have been reintroduced:

* [`/{business-id}/received_sharing_agreements`](/docs/marketing-api/reference/business/received_sharing_agreements/)
* [`/{business-id}/initiated_sharing_agreements`](/docs/marketing-api/reference/business/initiated_sharing_agreements/)

Both endpoints had previously been deprecated with the launch of [Graph API V6.0](/docs/graph-api/changelog/2020-02-03-endpoint-deprecations#business).

---

### Canvas

#### Deprecated Endpoints

*Deprecated in v8.0+.*

* [`/{canvas-id}/collection_hero_image`](https://developers.facebook.com/docs/graph-api/reference/v8.0/canvas)
* [`/{canvas-id}/collection_hero_video`](https://developers.facebook.com/docs/graph-api/reference/v8.0/canvas)
* [`/{canvas-id}/collection_thumbnails`](https://developers.facebook.com/docs/graph-api/reference/v8.0/canvas)

---

### Catalog API

#### Permissions

*Applies to v8.0+. Will apply to all versions on January 31, 2021.*

You no longer need the `ads_management` permission to access product catalog endpoints. Moving forward, you will need the `catalog_management` permission to call those endpoints. Developers who have had access to catalog endpoints via `ads_management` in the last 90 days will be automatically migrated to `catalog_management` permissions by August 14, 2020.

From now until February 28, 2021, developers using prior versions of the API are still able to call product catalog endpoints with the `ads_management` permission. If you are using v8.0, you must have `catalog_management` permission.

After the February deadline, the `catalog_management` permission will no longer be associated with `ads_management`, so users will have to explicitly grant `catalog_management` permission for your app.

#### Authentication

*Applies to v8.0+. Will apply to all versions on Nov 2, 2020.*

[[UPDATED]](#corrections) The following Catalog API endpoints now respect [two-factor authentication](https://www.facebook.com/business/help/280940009201586?id=199156230960298) Business settings. Any app calling this endpoint will receive an error if the Business that owns the catalog requires two-factor authentication for the current app user and the app user has not authenticated via two-factor.

When the current app user has access to the catalog through a partner business, we respect the authentication requirements from the partner’s Business Manager. System users do not have to authenticate via two-factor.

* [`POST /{business-id}/owned_product_catalogs`](/docs/marketing-api/reference/business/owned_product_catalogs/)
* [`POST /{destination-id}`](/docs/marketing-api/reference/destination)
* `POST /{home-listing-id}`
* `DELETE /{home-listing-id}`
* [`POST /{hotel-id}`](/docs/marketing-api/reference/hotel)
* [`DELETE /{hotel-id}`](/docs/marketing-api/reference/hotel)
* [`POST /{hotel-id}/hotel_rooms`](/docs/marketing-api/reference/hotel/hotel_rooms/)
* [`POST /{hotel-room-id}`](/docs/marketing-api/reference/hotel-room)
* [`DELETE /{hotel-room-id}`](/docs/marketing-api/reference/hotel-room)
* `POST /{page-id}/product_catalogs`
* [`POST /{product-catalog-id}`](/docs/marketing-api/reference/product-catalog)
* [`DELETE /{product-catalog-id}`](/docs/marketing-api/reference/product-catalog)
* `POST /{product-catalog-id}/agencies`
* `DELETE /{product-catalog-id}/agencies`
* [`POST /{product-catalog-id}/assigned_users`](/docs/marketing-api/reference/product-catalog/assigned_users/)
* [`DELETE /{product-catalog-id}/assigned_users`](/docs/marketing-api/reference/product-catalog/assigned_users/)
* `POST /{product-catalog-id}/batch`
* [`POST /{product-catalog-id}/categories`](/docs/marketing-api/reference/product-catalog/categories/)
* [`POST /{product-catalog-id}/destinations`](/docs/marketing-api/reference/product-catalog/destinations/)
* `POST /{product-catalog-id}/external_event_sources`
* `DELETE /{product-catalog-id}/external_event_sources`
* [`POST /{product-catalog-id}/flights`](/docs/marketing-api/reference/product-catalog/flights/)
* [`POST /{product-catalog-id}/home_listings`](/docs/marketing-api/reference/product-catalog/home_listings/)
* [`POST /{product-catalog-id}/hotel_rooms_batch`](/docs/marketing-api/reference/product-catalog/hotel_rooms_batch/)
* [`POST /{product-catalog-id}/hotels`](/docs/marketing-api/reference/product-catalog/hotels/)
* [`POST /{product-catalog-id}/items_batch`](/docs/marketing-api/reference/product-catalog/items_batch/)
* [`/{product-catalog-id}/pricing_variables_batch`](/docs/marketing-api/reference/product-catalog/pricing_variables_batch/)
* [`POST /{product-catalog-id}/product_groups`](/docs/marketing-api/reference/product-catalog/product_groups/)
* `POST /{product-catalog-id}/product_feeds`
* [`POST /{product-catalog-id}/product_sets`](/docs/marketing-api/reference/product-catalog/product_sets/)
* [`POST /{product-catalog-id}/products`](/docs/marketing-api/reference/product-catalog/products/)
* [`POST /{product-catalog-id}/vehicles`](/docs/marketing-api/reference/product-catalog/vehicles/)
* [`POST /{product-feed-rule-id}`](/docs/marketing-api/reference/product-feed-rule)
* [`DELETE /{product-feed-rule-id}`](/docs/marketing-api/reference/product-feed-rule)
* [`POST /{product-feed-id}`](/docs/marketing-api/reference/product-feed)
* [`DELETE /{product-feed-id}`](/docs/marketing-api/reference/product-feed)
* [`POST /{product-feed-id}/rules`](/docs/marketing-api/reference/product-feed/rules/)
* [`POST /{product-feed-id}/uploads`](/docs/marketing-api/reference/product-feed/uploads)
* `POST /{product-feed-id}/upload_schedules`
* [`POST /{product-feed-schedule-id}`](/docs/marketing-api/reference/product-feed-schedule/)
* [`DELETE /{product-feed-schedule-id}`](/docs/marketing-api/reference/product-feed-schedule/)
* [`POST /{product-feed-upload-id}/error_report`](/docs/marketing-api/reference/product-feed-upload)
* [`POST /{product-group-id}`](/docs/marketing-api/reference/product-group)
* [`DELETE /{product-group-id}`](/docs/marketing-api/reference/product-group)
* [`POST /{product-group-id}/products`](/docs/marketing-api/reference/product-group/products/)
* [`POST /{product-item-id}`](/docs/marketing-api/reference/product-item)
* [`DELETE /{product-item-id}`](/docs/marketing-api/reference/product-item)
* [`POST /{product-set-id}`](/docs/marketing-api/reference/product-set)
* [`DELETE /{product-set-id}`](/docs/marketing-api/reference/product-set)
* [`POST /{vehicle-id}`](/docs/marketing-api/reference/vehicle)

---

### Reporting

#### Deprecations

*Applies to v8.0+*

* `GET /{ad-study-id}?fields=split_test_config`
* `GET /{ad-study-id}?fields=iterative_split_test_config`

---

### Targeting

#### Deprecation

*Applies to v8.0+*

* `GET /search?type=adzipcode`

## Corrections

* September 28, 2020 — Updated the [Catalog API authentication entry](#catalog-api) for clarity.
* October 23, 2020 — Updated the [Catalog API entry](/docs/graph-api/changelog/version8.0#catalog-api):
  + We extended the deadline when developers using prior versions of the API are still able to call product catalog endpoints with the `ads_management` permission. The new deadline is February 28, 2021.
  + We added clarification about system user authentication.
* May 17, 2021 — Changed deprecated endpoint from [`GET /{place-id}`](/docs/graph-api/reference/place) to [`GET /{place-information-id}`](/docs/graph-api/reference/v7.0/place-information). [`GET /{place-id}`](/docs/graph-api/reference/place) was not deprecated.
