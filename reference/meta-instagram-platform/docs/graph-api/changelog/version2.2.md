## Version 2.2

[Graph API](#gapi-v2-2) | [Marketing API](#v2_2)

### Graph API

**Released** October 30, 2014 | **Available until** March 27, 2017

### New Features

* **Developers may now hide and unhide comments on a Page Post via the Graph API**:
  `POST /v2.2/{comment_id}?is_hidden=true` to hide, `POST /v2.2/{comment_id}?is_hidden=false` to unhide. You can determine if a comment is hidden, or if you have the ability to hide/unhide the comment by checking the `is_hidden` or `can_hide` fields on the [`comment`](/docs/graph-api/reference/v2.2/comment) node.
* **A new `token_for_business` field makes it easier to identify the same person across multiple apps owned by the same business:** In addition to the [Business Mapping API](/docs/apps/for-business), there is now a new `token_for_business` field on the [`user`](/docs/graph-api/reference/v2.2/user) object. This emits a token which is stable for the same person across multiple apps owned by the same [business](/docs/apps/for-business). This will only be emitted if the person has logged into the app. For games developers, this property will also be emitted via the `signed_request` object passed to a canvas page on load. Note that this is not an ID - it cannot be used against the Graph API, but may be stored and used to associate the app-scoped IDs of a person across multiple apps. Also note that if the owning business changes, this token will also change. If you request this field for an app which is not associated with a business, the API call will return an error.
* **The `comment` node has a new `object` field which emits the parent object on which the comment was made**.
  To get the ID and owner of the comment's parent object (for example, a Page Post) you might call: `/v2.2/{comment_id}?fields=object.fields(id,from)`
* **The Page node has a new edge to manage subscriptions for realtime updates**.

> * In previous versions, any app which was added as a Page Tab also received realtime updates. From v2.2 onwards there is a dedicated endpoint for managing these subscriptions:
>   + `GET /v2.2/{page-id}/subscribed_apps` returns the apps subscribed to realtime updates of the Page. This must be called with a Page Access Token.
>   + `POST /v2.2/{page-id}/subscribed_apps` subscribes the calling app to receive realtime updates of the Page. This must be called with a Page Access Token and requires the calling person to have at least the Moderator role on the Page.
>   + `DELETE /v2.2/{page-id}/subscribed_apps` stops the calling app from receiving realtime updates of the Page. This may be called with a Page or App Access Token. If called with Page Access Token, it requires the calling person to have at least the Moderator role on the Page.

* **The `feed_targeting` parameter is now supported when publishing videos to a Page**: `POST /v2.2/{page_id}/videos?feed_targeting={targeting_params}`. This lets you specify a number of parameters (such as age, location or gender) to help target who sees your content in News Feed. This functionality is already supported on `POST /{page_id}/feed` so we're extending this to videos too.
* **The Page node has a number of new writeable fields to let apps update a Page's information:** The following fields are now supported with POSTing to `/v2.2/{page_id}`:

> * `payment_options` takes an object which lets you specify the payment options accepted at the place.
> * `price_range` accepts an enum of strings which represent the self reported price range of the Page's business.
> * `latitude` and `longitude` can now be specified as properties of the `location` field in order to let apps programmatically update Page's physical location. Both are floats.
> * `ignore_coordinate_warnings` (boolean) determines if the API should throw an error when latitude and longitude are specified in location field for updating the Page's location. If set to false, an error will be thrown if the specified coordinates don't match with the Page's address.
> * `is_always_open` lets apps set the status of the place to “Always Open”. This can only be set to `true`, and will clear previously specified hours in `hours` field. To set specific hours, use `hours` field.
> * `is_published` takes a boolean which lets you publish or unpublish the Page. Unpublished pages are only visible to people listed with a role on the Page.
>   + **The Page node has a new readable field to let apps read a Page's information:** The following field are now supported with a GET to `/v2.2/{page_id}`:
> * `name_with_location_descriptor` returns a string which provides additional information about the Page's location besides its name.
>   + **There's a new `APPEARS_IN_RELATED_PAGES` setting on `/v2.2/{page_id}/settings`**. This boolean determines if your page can be included in the list of suggested pages which are presented when they like a page similar to yours. You may set or read this value.
>   + **You can now read the permissions your app has been approved for via an API.** A new edge on your App object, called [`/{app-id}/permissions`](/docs/graph-api/reference/v2.2/app/permissions), allows you to view the permissions that your app has been approved for via Login Review.

### Changes

* There's now a limit of 50 IDs which can specified in a single request using the syntax `?ids=ID1,ID2`. This reduces the likelihood of timeouts when requesting data about a large number of IDs in a single request.
* The `blocked` edge on the Page node now requires a Page Access Token - this endpoint can no longer be called with an App or User token. That endpoint is available at: `GET|POST|DELETE /v2.2/{page_id}/blocked?access_token={page_access_token}`.
* The `tabs` edge on the Page node now requires a Page token for GETs. POSTs and DELETEs on this endpoint already require page tokens. That endpoint is available at: `GET|POST|DELETE /v2.2/{page_id}/tabs?access_token={page_access_token}` Calling GET on this edge now works for people in the 'Analyst' role. It previously required the 'Editor' role.
* The `tabs` edge on the Page node will now throw an error if the caller does not have permission. Previously it would only return an empty string.
* The `/{page_id}/admins` edge on the Page node has been renamed to `/v2.2/{page_id}/roles`. In addition, in the response, the values returned in the role field have been changed:

> * `MANAGER` has been renamed to `Admin`.
> * `CONTENT_CREATOR` has been renamed to `Editor`.
> * `MODERATOR` has been renamed to `Moderator`.
> * `ADVERTISER` has been renamed to `Advertiser`.
> * `INSIGHTS_ANALYST` has been renamed to `Analyst`.

* The `settings` edge on the Page node will no longer include entries for settings where the `value` field would be null.
* `POST /{page_id}/settings` will no longer support the `setting` and `value` params. Instead, you should specify the `option` param which should be an object containing a single key/value pair with the setting enum as the key.
* From v2.2 onwards, apps calling `GET /v2.2/{page_id}/notifications` must use a Page Access Token. Previously this required the `manage_notifications` permission. User Access Tokens will no longer work for this endpoint.
* The structure of the `/v2.2/{group_id}/albums` endpoint has changed to match the response of `/{user_id}/albums`.
* The number of results returned from the `/v2.2/me/friends` endpoint now defaults to 25.

### 90-day deprecations (effective Wednesday, January 28, 2015)

* The `fb:name` social plugin has been deprecated and will stop working on Jan 28, 2015. Developers should instead use the `FB.api()` method of the Javascript SDK to retrieve the names of users.
* In versions previous to v2.2, it was possible for an app to see if a person like the app's page by checking the `page_fan` FQL table or the `/{user_id}/likes/{app_page_id}` Graph API endpoint without needing the `user_likes` permission. Starting in v2.2, the `user_likes` permission will be required to query these endpoints. Also, we will require the `user_likes` permission on versions older than v2.2 starting 90 days from today, on Jan 28, 2015. Facebook will not grant the `user_likes` permission solely for the purpose of checking if a person has liked an app's page. This change was announced on August 7, 2014 and will come into effect on November 5, 2014.
* The Pages JSON feed (e.g. https://www.facebook.com/feeds/page.php?id=%2019292868552&format=json) is now deprecated and will stop returning data from Jan 28, 2015 onwards. Developers should instead call the feed edge on the Graph API's Page object: `/v2.2/{page_id}/feed`.
* `POST /{page-id}/tabs` and `DELETE /{page-id}/tabs` will no longer support subscribing or unsubscribing an app for realtime updates. This will take effect in all previous API versions on January 28, 2015. To subscribe an app to realtime updates for a page, use the new `/v2.2/{page_id}/subscribed_apps` endpoint.
* The [Comments Plugin](/docs/plugins/comments) will no longer support commenting via third-party identifiers after January 28, 2015. This facility was rarely used and the majority of comments posted by these accounts were of low quality. People may still comment using their Facebook account, or may also comments as a Facebook Page.

### Disabled SSL 3.0 Support

On October 14, 2014, we dropped support for SSL 3.0 across Facebook properties, including the Facebook Platform API and the Real-Time Updates API, after a vulnerability in the protocol was [revealed on October 14, 2014](http://l.facebook.com/l.php?u=http%3A%2F%2Fgoogleonlinesecurity.blogspot.com%2F2014%2F10%2Fthis-poodle-bites-exploiting-ssl-30.html&h=AUBued9e1er7v7yHdxw4A87e6Y_KFiv5vQ5P_chcKr56yaUUcOnSrYH3V56PdzzBszLXvlJQeNE809wlcC0iIkDdls0lQqTDl3fLFvfqxNMwDM1Z-FWbD3kj32CuBq3zDK1sVr9sdSRyyPFt). This change helps protect people’s information.

If your HTTP library forces the use of SSL 3.0 rather than TLS, you will no longer be able to connect to Facebook. Please update your libraries and/or configuration so that TLS is available.

### Marketing API

**Released** October 30, 2014 | **Available until** July 8, 2015

This is Facebook's first new API update after versioning was announced. API versions are supported for 90 days after the next version is released. This means that version 2.1 would be available until 90 days from `v2.2`, January 28, 2015. However, we have extended the adoption timeline for `v2.2` this time to March 11, 2015. For more information, please see our [blog post](https://developers.facebook.com/ads/blog/post/2014/12/16/ads_api_version_2_2_extension/).

### Changes

The below is a summarized list of all changes. For more info on upgrading, including code samples, please see our [expanded upgrade guide](/docs/reference/ads-api/upgrading).

#### Bid and Targeting

* `targeting` and `bid_type` will be required at ad set level, and will no longer be available at ad level.
* `bid_info` will be required at ad set level, while optional at ad level.
* Action Spec targeting, which is a beta feature, will no longer be supported.

Affected Endpoints:

* `/act_{AD_ACCOUNT_ID}/adgroups`
* `/act_{AD_ACCOUNT_ID}/adcampaigns`
* `/{CAMPAIGN_GROUP_ID}/adcampaigns`
* `/{CAMPAIGN_GROUP_ID}/adgroups`
* `/{AD_SET_ID}/adgroups`
* `/{AD_SET_ID}`
* `/{AD_ID}`

#### Required promoted\_object field on Ad Set creation

A new field `promoted_object` will be required for creating an ad set when the campaign objective is website conversions, page likes, offer claims, mobile app install/engagement or canvas app install/engagement.

* It will need to be set at creation and cannot be changed, if it needs to be changed a new ad set must be created.
* Existing ad sets without a `promoted_object` will not be allowed to set a `promoted_object`. You must create a new ad set if you want to specify a `promoted_object`. Those existing ad sets without that setting will still run, and still can be updated/deleted as usual.
* When `promoted_object` is specified, `conversion_specs` will be automatically inferred from the `objective` and `promoted_object` combo and cannot be changed/overwritten.
* Additional validation will occur to ensure the ad is promoting the same object as specified in `promoted_object`.

Affected Endpoints:

* `/{AD_SET_ID}`

#### Reach and Frequency

* The `target_specs` endpoint will be replaced with `target_spec`, only allowing for one spec per prediction.
* The new `target_spec` field returns an object where `target_specs` used to return an array.
* A new field, `story_event_type`, will be added. This field will be used to specify when an ad set may or may not have video ads and is required when targeting **all** mobile devices.

#### Custom Audience Targeting

* Advertisers will need to specify one or many App IDs when **adding, removing, or opt-ing out users** from Custom Audiences based on the Facebook user ID or app-scoped user ID.
* By requiring an App ID, Facebook is ensuring that the Custom Audiences created only include IDs associated with people who have actually logged in or engaged with an advertiser’s app.
* The `app_ids` field is required when `"schema"="UID"`.

#### New Graph API framework conversion

Starting with version 2.2 the following changes will be in affect for the endpoints below.

* OAuthInsufficientScopeException will now be replaced by a GraphMethodException.
* `count`, `offset`, and `limit` will no longer be returned and you must instead use a [cursor-based](/docs/graph-api/using-graph-api/v2.1#paging) approach to paging.
* `total_count` is only returned when the flag `summary=true` is set.

Affected Endpoints:

* `/act_{AD_ACCOUNT_ID}/asyncadgrouprequestsets`
* `/act_{AD_ACCOUNT_ID}/adreportschedules`
* `/{SCHEDULE_REPORT_ID}/adreportruns`
* `/act_{AD_ACCOUNT_ID}/stats`
* `/act_{AD_ACCOUNT_ID}/adcampaignstats`
* `/act_{AD_ACCOUNT_ID}/adgroupstats`
* `/act_{AD_ACCOUNT_ID}/conversions`
* `/act_{AD_ACCOUNT_ID}/adcampaignconversions`
* `/act_{AD_ACCOUNT_ID}/adgroupconversions`
* `/act_{AD_ACCOUNT_ID}/connectionobjects`
* `/act_{AD_ACCOUNT_ID}/partnercategories`
* `/act_{AD_ACCOUNT_ID}/reachfrequencypredictions`
* `/act_{AD_ACCOUNT_ID}/asyncadgrouprequestsets`
* `/act_{AD_ACCOUNT_ID}/broadtargetingcategories`
* `/act_{AD_ACCOUNT_ID}/targetingsentencelines`
* `/act_{AD_ACCOUNT_ID}/ratecard`
* `/act_{AD_ACCOUNT_ID}/reachestimate`
* `/act_{AD_ACCOUNT_ID}/users`
* `/{AD_ACCOUNT_GROUP}/users`
* `/{AD_ACCOUNT_GROUP}/adaccounts`
* `/{CAMPAIGN_ID}/asyncadgrouprequests`
* `/{ADGROUP_ID}/reachesttimate`
* `/{ADGROUP_ID}/keywordstats`
* `/{ADGROUP_ID}/targetingsentencelines`
* `/search?type=adgeolocation (location_types: city, region)`
* `/search?type=adlocale`
* `/search?type=adworkemployer`
* `/search?type=adworkposition`
* `/search?type=adeducationschool`
* `/search?type=adzipcode`
* `/search?type=adcountry`
* `/search?type=adcity`
* `/{CUSTOM_AUDIENCE_ID}/users`
* `/{CUSTOM_AUDIENCE_ID}/adaccounts`
* `/{REACH_FREQUENCY_PREDICTIONS_ID}/`
* `/{ASYNC_REQUEST_SET_ID}/`
* `/{ASYNC_REQUEST_SET_ID}/requests/`
* `/{ASYNC_REQUEST_ID}`
* `/{USER_ID}adaccounts` which has additional changes:
* `business` returns an ID rather than an object.
* `users` returns a object with fields `id` rather than `uid`, `permissions`, and `role`.
* A new field, `created_time`, which is the time that the account was created.
