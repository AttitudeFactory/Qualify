# Version 14.0

## Graph API

**Released** May 25, 2022 | **Available until** September 17, 2024 | [Blog post](/blog/post/2022/05/25/introducing-facebook-graph-api-v14-marketing-api-v14/)

### Instagram Graph API

#### Insights

*Applies to v14.0+.*

The [`end_time`](/docs/instagram-api/reference/ig-user/insights#metrics-and-periods) JSON property will not be returned for any audience\_\* metrics.

### Instagram Messaging API

#### User Profile

*Applies to v14.0+*

You can now use the [User Profile API](/docs/messenger-platform/instagram/features/user-profile) to get an app user's `username`.

### Payments

#### Risk action type

*Applies to v14.0+.*

The `risk` action type of the `actions` field ([`GET /{payment-id}?fields=actions`](/docs/graph-api/reference/payment#fields)) has been removed and will not be returned.

### Permissions

#### user\_likes

*Applies to all versions.*

The [user\_likes](/docs/permissions/reference/user_likes) permission's allowed usage has changed. The new allowed usage is:

* Provide a personalized experience by correlating or surfacing content related to the person’s likes. This includes curating content at scale to customize apps with large amounts of content and to enable people to share their likes with others, such as in the case of dating and music apps.
* Allow parental access controls and monitoring apps to analyze user likes for potential safety and wellbeing issues for people under 18 years old, as used solely by parents and guardians for under 18 year old dependents and limited to youth social media analysis as presented in the app’s user interface.

#### user\_posts

*Applies to all versions.*

The [user\_posts](/docs/permissions/reference/user_posts) permission's allowed usage has changed. The new allowed usage is:

* Enable people to create physical or digital books or albums of their timelines, and to share memories from their timeline on Facebook or on other social apps.
* Allow parental access controls and monitoring apps to analyze a post's content to detect potential risk to safety or wellbeing for people under 18 years old, as used solely by parents and guardians for under 18 year old dependents and limited to youth social media analysis as presented in the app’s user interface.

### WhatsApp

See the [Whatsapp changelog](/docs/whatsapp/business-platform/changelog).

## Marketing API

The expiration date for Marketing API v14.0 and v15.0 has been moved to September 20, 2023 from August 15, 2023 to provide more time for the platform integrating changes for [DSA enforcement](https://www.facebook.com/business/help/605021638170961). Note v14.0 and v15.0 will expire on the same day. To avoid disruption to your apps, we recommend upgrading to our latest version before September 20.

**Released** May 25, 2022 | **Available until** September 20, 2023 | [Blog post](/blog/post/2022/05/25/introducing-facebook-graph-api-v14-marketing-api-v14/)

No changes.
