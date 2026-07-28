## Version 2.1

### Graph API v2.1

**Released** August 7, 2014 | **Available until** October 31, 2016

This is Facebook's first new API update after version 2.0 was launched at the 2014 f8 conference. API versions are supported for two years after the next version is released. This means that:

* Version 2.1 will be available starting today until two years after the release of a post-v2.1 version.
* Version 2.0 will expire on August 7, 2016, two years after the release of v2.1. (Version 2.0 was introduced on April 30, 2014.)
* Version 1.0 will expire as scheduled on April 30, 2015.

### New Features

* **Pages can mention other Pages when publishing via API:** When making calls to several [Page publishing edges](/docs/graph-api/reference/v2.1/page/) such as /feed or /photos you can now mention other Pages in a message field. This extends our current availability of [mentions in Open Graph](/docs/opengraph/using-actions/v2.0#pages). This API requires review by Facebook before it can be used by people other than the app’s developers. Learn more about the Page Mentions review process in our [documentation](/docs/apps/review/login#pagementions).
* **New total friend count on the friends connection:** [/v2.1/me/friends](/docs/graph-api/reference/v2.1/user/friends/) (and [/v2.0/me/friends](/docs/graph-api/reference/v2.1/user/friends/)) now provides access to total friend count - this count includes friends who use the app as well as those who don't.
* **New 'facebook-api-version' HTTP header:** In all API versions, we now return an HTTP response header called 'facebook-api-version' which indicates which API version your app is actually experiencing - this may be different to the API version you specify in your request due to upgrades.
* **New App Insights API:** v2.1 includes access to the new [App Insights data via an API](/docs/graph-api/reference/v2.1/app/app_insights). This is available by calling /v2.1/{app\_id}/app\_insights
* **A new format for Graph API Field Expansion:** v2.1 introduces more concise syntax for Field Expansion. (The new syntax is also been added to v2.0 and earlier). See our documentation on [field expansion](/docs/graph-api/using-graph-api/v2.1#fieldexpansion) for examples. The older format for field expansion is still available, but the new format is preferred.
* **User-facing error messages**: In some cases (such as access token invalidation or expiry) the API now returns user-displayable error messages which describe the error and what the person may need to do to resolve it. These error messages will be returned in US English by default, but if you query the Graph API specifying the locale parameter (e.g. ?locale=es\_ES) the string may be returned in the specified language.
* **The Event object now has five new integer fields: attending\_count, declined\_count, maybe\_count, noreply\_count and invited\_count:** Each of these returns an integer which represents the number of people who have been invited, not replied, are attending, are not attending or whom may attend.
* **GET /v2.1/?id={url} returns a new [URL node](/docs/graph-api/reference/v2.1/url):** In v2.1, when you query the Graph API with a URL as the ID, we'll return a URL object which enumerates any share info available for that URL, any Open Graph object associated with that URL, or any AppLinks that use the URL.
* **The Page object now has a [new `screennames` edge](/docs/graph-api/reference/v2.1/page/screennames)**: this returns a list of the other, non-Facebook accounts associated with the brand or entity represented by a Facebook Page.

### Deprecations

* **The FQL and REST APIs are no longer available in v2.1:** Previously announced with v2.0, apps must migrate to versioned Graph API calls starting with v2.1.
* **The '/insights' edge on the Application object is no longer available in this version:** This has been replaced by the new '/app\_insights' edge.

### **90-Day Deprecations**

The following deprecations will take place on November 5, 2014 - 90 days after the launch of v2.1.

* **The [Recommendations Bar](/docs/plugins/recommendations-bar) social plugin has been deprecated:** On Wednesday November 5th 2014, the Recommendations Bar will no longer render on any website. If you're using this plugin, we recommend you remove it from your site before this date.
* **The /insights edge on the Application object will be removed in both v1.0 and v2.0:** The insights API is classified as an Extended API and is subject to change within the life of a version. Developers should instead move to call [/v2.1/{app\_id}/app\_insights](/docs/graph-api/reference/v2.1/app/app_insights) before this deprecation takes effect.
* **The '[liked](/docs/reference/login/signed-request)' property will no longer be returned in the ['signed\_request' object](/docs/reference/login/signed-request) for Page Tab apps created after today.** From November 5, 2014 onwards, the 'liked' property will always return 'true' regardless of whether or not the person has liked the page.

### Changes

1. **API responses are now always JSON objects, rather than booleans, integers or strings:** Many API calls before v2.1 returned plain text 'true' or a raw number like '378293782' as the response. With v2.1, those calls will now return valid JSON, such as: `{ “success”: true }`
2. **The dialogs/oauth endpoint no longer support the 'return\_session' and 'session\_version' parameters** for legacy authentication methods.
3. **/v2.1/me/permissions no longer contains the 'installed' permission:** 'installed' was a pseudo-permission that was used to check if someone had your app installed. Instead of looking for 'installed' in the response, you should call the endpoint and, if it returns data, consider this indication that the user has installed the app.
4. **GET /?id={your\_url} for Open Graph object and Shares has been replaced by new [URL node](/docs/graph-api/reference/v2.1/url):** Previously, when you queried the Graph API with a URL as the ID, we returned information related to shares of that URL. If the URL was also an Open Graph object, you would have to specify 'type=og' in your request. Version 2.1 introduces a [new URL node](/docs/graph-api/reference/v2.1/url) which combines and replaces this functionality.
5. **/v2.1/{post-id} will now return all photos attached to the post:** In previous versions of the API only the first photo was returned with a post. This removes the need to use FQL to get all a post's photos.
6. **'uri' can no longer be requested from picture fields:** Apps previously requesting `uri` should instead use `url`.

### Changes to Platform Policies

* Games which include mandatory or optional in-app charges must now disclose this in their app's description, either on Facebook or other platforms it supports. This is to give people a clear indication that your game may charge people during gameplay.
* You must not incentivize people to use social plugins or to like a Page. This includes offering rewards, or gating apps or app content based on whether or not a person has liked a Page. It remains acceptable to incentivize people to login to your app, checkin at a place or enter a promotion on your app's Page. To ensure quality connections and help businesses reach the people who matter to them, we want people to like Pages because they want to connect and hear from the business, not because of artificial incentives. We believe this update will benefit people and advertisers alike.

These policy changes will come into effect on November 5, 2014 - 90 days after the launch of v2.1. They apply to all apps across all API versions.
