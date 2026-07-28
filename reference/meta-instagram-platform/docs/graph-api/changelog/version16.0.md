# Version 16.0

## Graph API

**Released** February 2, 2023 | **Available until** May 14, 2025 | [Blog post](/blog/post/2023/02/02/introducing-facebook-graph-and-marketing-api-v16/)

### Comment, Photo, Post, Video

*Applies to v16.0+. Will apply to all versions May 3, 2023.*

The following fields on [comments](/docs/graph-api/reference/comment), [photos](/docs/graph-api/reference/photo), [posts](/docs/graph-api/reference/post), and [videos](/docs/graph-api/reference/video) created on a user profile will now return an empty data set:

* `comments`
* `message_tags`
* `reactions`
* `sharedposts`
* `story`
* `story_tags`
* `to`
* `via`

### Encryption

*Applies to v16.0+. Will apply to all version May 3, 2023.*

TLS versions older than 1.2 and static RSA cipher suites are no longer supported. See [Encryption](/docs/graph-api/guides/secure-requests#encryption).

### Messenger Platform

See the [Messenger Platform](https://developers.facebook.com/docs/messenger-platform/changelog) changelog.

### WhatsApp Business Platform

See the [WhatsApp Business Platform](/docs/whatsapp/business-platform/changelog#february-2--2023) changelog.

## Marketing API

**Released** February 2, 2023 | **Available until** February 6, 2024 | [Blog post](/blog/post/2023/02/02/introducing-facebook-graph-and-marketing-api-v16/)

### Ads Placement

#### Instant Articles

*Applies to v16.0+. Will apply to all versions on April 20, 2023.*

Advertisers will no longer be able to target the Instant Article placement for ads creation.

The following endpoints will be affected:

* [`GET /{ad-account-id}/adsets`](/docs/marketing-api/reference/ad-campaign#Reading)
* [`POST /{ad-account-id}/adsets`](/docs/marketing-api/reference/ad-campaign#Creating)
* [`GET /{ad-set-id}?fields=targeting`](/docs/marketing-api/reference/ad-campaign#fields)

### Travel Ads

#### Flight Ad Prospecting

*Applies to v16.0+.*

Prospecting is no longer an available audience option when creating a flight ad. New campaigns will only including retargeting audiences and require a data source.

The following endpoints and fields are affected:

* [`POST /{ad-account-id}/adsets`](/docs/marketing-api/reference/ad-campaign#Creating)

#### Trip Consideration

*Applies to v16.0+.*

The **Reach Potential Travelers** option is no longer available. System improvements will automatically prioritize delivery to Account Center accounts that may be planning travel. Campaigns are expected to achieve similar performance.

The following endpoints are affected:

* [`POST /{ad-account-id}/adsets`](/docs/marketing-api/reference/ad-campaign#Creating)
