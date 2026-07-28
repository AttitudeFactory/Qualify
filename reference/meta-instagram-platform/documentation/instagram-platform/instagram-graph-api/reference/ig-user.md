# IG User



Represents an [Instagram Business Account](https://help.instagram.com/502981923235522) or an [Instagram Creator Account](https://help.instagram.com/1158274571010880).

Throughout our documentation we use &quot;Instagram User&quot; and &quot;Instagram Account&quot; interchangeably. Both represent your app user&#039;s Instagram professional account.

### Requirements

|  | Instagram API with Instagram Login | Instagram  API with Facebook Login |
| --- | --- | --- |
| **Access Tokens** | * Instagram User user access token | * [Facebook User access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) |
| **Host URL** | `graph.instagram.com` | `graph.facebook.com` |
| **Login Type** | Business Login for Instagram | Facebook Login for Business |
| [**Permissions**](https://developers.facebook.com/docs/permissions/reference#i) | * `instagram_business_basic` | * `instagram_basic`&lt;br&gt;* `pages_read_engagement`&lt;br&gt;&lt;br&gt;If the app user was granted a role via the Business Manager on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to the targeted IG User, you will also need one of:&lt;br&gt;&lt;br&gt;* `ads_management`&lt;br&gt;* `ads_read`&lt;br&gt;&lt;br&gt;If you are requesting the `shopping_product_tag_eligibility` field for [product tagging](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/product-tagging), you will also need:&lt;br&gt;&lt;br&gt;* `catalog_management`&lt;br&gt;* `instagram_shopping_tag_products` |
| **[Business Roles](https://www.facebook.com/business/help/442345745885606)** | Not applicable. | If you are requesting the `shopping_product_tag_eligibility` field for [product tagging](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/product-tagging), the app user must have an admin role on the [Business Manager](https://business.facebook.com/) that owns the IG User&#039;s [Instagram Shop](https://help.instagram.com/1187859655048322). |
| **[Instagram Shop](https://help.instagram.com/1187859655048322/)** | Not applicable. | If you are requesting the `shopping_product_tag_eligibility` field for [product tagging](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/product-tagging), the IG User must have an approved [Instagram Shop](https://help.instagram.com/1187859655048322/) with a product catalog containing products. |

## Creating &#123;#create&#125;

This operation is not supported.

## Reading &#123;#read&#125;

**`GET /&lt;IG_USER_ID&gt;`**

Get fields and edges on an Instagram Business or Creator Account.

**Warning:** If you are migrating from Marketing API Instagram Ads endpoints to Instagram Platform endpoints, be aware that some field names are different.

### Request Syntax

```curl
GET https://graph.facebook.com/&lt;API_VERSION&gt;/&lt;IG_USER_ID&gt;
  ?fields=&lt;LIST_OF_FIELDS&gt;
  &amp;access_token=&lt;ACCESS_TOKEN&gt;
```

### Path Parameters

| Placeholder | Value |
| --- | --- |
| `&lt;API_VERSION&gt;` | API [version](https://developers.facebook.com/docs/graph-api/guides/versioning). |
| `&lt;IG_USER_ID&gt;` | **Required.** IG User ID. |

### Query String Parameters

| Key | Placeholder | Value |
| --- | --- | --- |
| `access_token` | `&lt;ACCESS_TOKEN&gt;` | **Required.** App user&#039;s [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) access token. |
| `fields` | `&lt;LIST_OF_FIELDS&gt;` | Comma-separated list of IG User [fields](#fields) you want returned for each IG User in the result set. |

### Fields

Public fields can be returned by an edge using field expansion. Only a few fields will be available for accessing [Page-backed Instagram accounts](https://developers.facebook.com/documentation/ads-commerce/instagram/ads-api/guides/pages-ig-account#pbia).

| Field Name | Description |
| --- | --- |
| `alt_text`  &lt;br&gt;Public | Descriptive text for images, for accessibility. |
| `biography`  &lt;br&gt;Public | Profile bio text. |
| `followers_count`  &lt;br&gt;Public | Total number of Instagram users following the user. |
| `follows_count` | Total number of Instagram users the user follows. |
| `has_profile_pic` | Indicates whether your app user&#039;s Instagram professional account has a profile picture. |
| `id`  &lt;br&gt;Public | App-scoped User ID. Available for Page-backed Instagram accounts. |
| `is_published` | Indicates whether your app user&#039;s Instagram account is published. Available for Page-backed Instagram accounts. |
| `legacy_instagram_user_id` | Your app user&#039;s Instagram ID that was created for Marketing API endpoints for v21.0 and older. Available for Page-backed Instagram accounts. |
| `media_count`  &lt;br&gt;Public | Total number of IG Media published on your app user&#039;s account. |
| `name` | Your app user&#039;s Instagram profile name. |
| `profile_picture_url` | Your app user&#039;s Instagram profile picture URL. |
| `collaborative_media_search` | Look up a specific collaborative media by ID. Access via field expansion. Available for Instagram API with Facebook Login only. |
| `shopping_product_tag_eligibility` | Returns `true` if your app user has set up an [Instagram Shop](https://help.instagram.com/1187859655048322/) and is therefore eligible for product tagging, otherwise returns `false`. |
| `username`  &lt;br&gt;Public | Your app user&#039;s Instagram profile username. |
| `website`  &lt;br&gt;Public | Your app user&#039;s website URL. |

### Edges

| Edge | Description |
| --- | --- |
| [`agencies`](https://developers.facebook.com/docs/instagram-api/reference/ig-user/agencies) | A list of businesses that can advertise for this Instagram professional account. |
| [`authorized_adaccounts`](https://developers.facebook.com/docs/instagram-api/reference/ig-user/authorized-adaccounts) | Ad accounts that can advertise for this Instagram professional account. |
| [`business_discovery`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/business_discovery) | Get data about other Instagram Business or Instagram Creator [IG Users](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user). |
| [`connected_threads_user`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/connected_threads_user) | Represents a Threads account connected to an Instagram account. |
| [`content_publishing_limit`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/content_publishing_limit) | Represents an [IG User&#039;s](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) current [content publishing](https://developers.facebook.com/documentation/instagram-platform/content-publishing) usage. |
| [`insights`](https://developers.facebook.com/documentation/instagram-platform/api-reference/instagram-user/insights) | Represents social interaction metrics on an [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user). |
| [`instagram_backed_threads_user`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/instagram_backed_threads_user) | Represents a Threads account backed by an Instagram account. |
| [`live_media`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/live_media) | Represents a collection of live video [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) on an [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user). |
| [`media`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media) | Represents a collection of [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) on an [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user). |
| [`media_publish`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media_publish) | Publish an [IG Container](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container) on an Instagram Business [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user). |
| [`mentions`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/mentions) | Create an [IG Comment](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment) on an IG Comment or captioned [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) that an [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) has been &#064;mentioned in by another Instagram user. |
| [`mentioned_comment`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/mentioned_comment) | Get data on an [IG Comment](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment) in which an [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) has been &#064;mentioned by another Instagram user. |
| [`mentioned_media`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/mentioned_media) | Get data on an [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) in which an [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) has been &#064;mentioned in a caption by another Instagram user. |
| [`recently_searched_hashtags`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/recently_searched_hashtags) | Get [IG Hashtags](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-hashtag) that an [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) has searched for within the last 7 days. |
| [`stories`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/stories) | Represents a collection of story [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) objects on an [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user). |
| [`tags`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/tags) | Represents a collection of [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) in which an [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) has been tagged by another Instagram user. |
| [`upcoming_events`](https://developers.facebook.com/docs/instagram-api/reference/ig-user/upcoming-events) | A list of events this Instagram professional account is hosting. |
| [`collaboration_invites`](https://developers.facebook.com/docs/instagram-api/reference/ig-user/collaboration_invites) | Represents a collection of [`IG Media`](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) object attributes (media_id, media_owner_username, caption, media_url) for which the IG user has been invited for collaboration. |
| [`collaborative_media`](https://developers.facebook.com/docs/instagram-api/reference/ig-user/collaborative_media) | Represents a collection of [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) where the IG User is an accepted collaborator. Does not include media the user owns directly. Available for Instagram API with Facebook Login only. |

### Response

A JSON-formatted object containing default and requested [fields](#fields) and [edges](#edges).

```json
&#123;
  &quot;&lt;FIELD&gt;&quot;:&quot;&lt;VALUE&gt;&quot;,
  ...
&#125;
```

### cURL Example

#### Request

```curl
curl -X GET \
  &#039;https://graph.facebook.com/v25.0/17841405822304914?fields=biography%2Cid%2Cusername%2Cwebsite&amp;access_token=EAACwX...&#039;
```

#### Response

```json
&#123;
  &quot;biography&quot;: &quot;Dino data crunching app&quot;,
  &quot;id&quot;: &quot;17841405822304914&quot;,
  &quot;username&quot;: &quot;metricsaurus&quot;,
  &quot;website&quot;: &quot;http://www.metricsaurus.com/&quot;
&#125;
```

## Updating

This operation is not supported.

## Deleting

This operation is not supported.
