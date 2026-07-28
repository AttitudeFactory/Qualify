# Set Up Webhooks for Instagram

Webhooks for [Instagram](/docs/instagram-api) allow you to receive real-time notifications whenever someone comments on the Media objects of your app users; [@mentions](https://developers.facebook.com/docs/pages/mentions) your app users; or when Stories of your app users expire.

## Receive Live Webhook Notifications

To receive live webhook notifications, the following conditions must be satisfied:

* Your app must have **Instagram** webhooks configured and appropriate **fields** subscribed to in the App Dashboard.
* For [Consumer apps](https://developers.facebook.com/docs/development/create-an-app/app-dashboard/app-types#consumer), they must be in [Live Mode.](/docs/development/build-and-test/app-modes#live-mode)
* For [Business apps](https://developers.facebook.com/docs/development/create-an-app/app-dashboard/app-types#business), they must have permissions with an [Advanced Access](https://developers.facebook.com/docs/graph-api/overview/access-levels#advanced-access) level. You can request Advanced Access for permissions as shown here:

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=482444916912676&version=1736178359)

If the app permissions don't have an access level of **Advanced Access**, the app doesn't receive webhook notifications.

* The app user must have granted your app appropriate permissions ([instagram\_manage\_insights](/docs/permissions/reference/instagram_manage_insights) for Stories, [instagram\_manage\_comments](/docs/permissions/reference/instagram_manage_comments) for Comments and @Mentions).
* The Page connected to the app user's account must have [Page subscriptions enabled](/docs/instagram-api/guides/webhooks/#step-2--enable-page-subscriptions).
* The Business connected to the app user's Page must be **verified**.
* The owner of the Media object upon which the comment or @mention appears must not have set their account to [private](https://www.facebook.com/help/instagram/448523408565555).

### Limitations

* Webhook notifications for Comments on albums don't include the album ID. Get the album ID by querying the Comment ID in the webhook and request its `media` field.
* Apps don't receive a webhook notifications if the Media where the comment or @mention appears was created by a [private account](https://www.facebook.com/help/instagram/448523408565555).
* Story insights metrics with counts of less than 5 are returned as `-1`.
* Apps only receive webhook notifications for comments on live [IG Media](https://developers.facebook.com/docs/instagram-api/reference/ig-media/) if the media is on broadcast.
* Reels are not supported.
* Your app must have successfully completed App Review (advanced access) to receive webhooks notifications for `comments` and `live_comments` webhooks fields.
* If the media is used for dynamic ads, the ad ID will not be returned.

## Step 1: Create an Endpoint

[Create an endpoint](/docs/graph-api/webhooks/getting-started) that accepts and processes webhooks. During the [configuration](https://developers.facebook.com/docs/graph-api/webhooks/getting-started#configure-webhooks-product), select the **Instagram Graph API** object, click **Set up**, and subscribe to one or more [Instagram fields](/docs/graph-api/webhooks/reference/instagram/).

### Instagram Fields

Field | Description | Permissions Required || [`comments`](/docs/graph-api/webhooks/reference/instagram/#comments) | Comments on an [IG Media](/docs/instagram-api/reference/ig-media/) owned by your app's Instagram user.  The `ad_id`, `ad_title` and `original_media_id` will be returned in the media object when a person comments on a boosted Instagram post or Instagram ads post. | * [instagram\_manage\_comments](/docs/permissions/reference/instagram_manage_comments) * [pages\_manage\_metadata](/docs/permissions/reference/pages_manage_metadata) * [pages\_read\_engagement](/docs/permissions/reference/pages_read_engagement) **or**    [pages\_show\_list](/docs/permissions/reference/pages_show_list) |
| [`live_comments`](/docs/graph-api/webhooks/reference/instagram/#live_comments) | Comments on a live [IG Media](/docs/instagram-api/reference/ig-media/) owned by your app's Instagram user. | * [instagram\_manage\_comments](/docs/permissions/reference/instagram_manage_comments) * [pages\_manage\_metadata](/docs/permissions/reference/pages_manage_metadata) * [pages\_read\_engagement](/docs/permissions/reference/pages_read_engagement) **or**    [pages\_show\_list](/docs/permissions/reference/pages_show_list) |
| [`mentions`](/docs/graph-api/webhooks/reference/instagram/#mentions) | @mentions for your app's Instagram user in a comment. | * [instagram\_manage\_comments](/docs/permissions/reference/instagram_manage_comments) * [pages\_manage\_metadata](/docs/permissions/reference/pages_manage_metadata) * [pages\_read\_engagement](/docs/permissions/reference/pages_read_engagement) **or**    [pages\_show\_list](/docs/permissions/reference/pages_show_list) |
| [`story_insights`](/docs/graph-api/webhooks/reference/instagram/#story_insights) | Metrics describing interactions on a story. Sent 1 hour after the story expires. | * [instagram\_manage\_insights](/docs/permissions/reference/instagram_manage_insights) * [pages\_manage\_metadata](/docs/permissions/reference/pages_manage_metadata) * [pages\_read\_engagement](/docs/permissions/reference/pages_read_engagement) **or**    [pages\_show\_list](/docs/permissions/reference/pages_show_list) |

## Step 2: Enable Page Subscriptions

Your app must enable Page subscriptions on the Page connected to the app user's account by sending a `POST` request to the [Page Subscribed Apps](/docs/graph-api/reference/page/subscribed_apps#Creating) edge and subscribing to any Page field.

### Endpoint Requirements

* the app user's Page Access Token
* [pages\_manage\_metadata](docs/permissions/reference/pages_manage_metadata)

#### Request Syntax

```
POST /{page-id}/subscribed_apps
  ?access_token={access-token}
  &subscribed_fields={fields}
```

#### Request Parameters

Value Placeholder | Value Description || `{page_id}` | ID of the Page connected to the app user's account. |
| `{access_token}` | App user's Page access tToken. |
| `{fields}` | A Page field (example: `feed`). |

Your app does not receive notifications for changes to a field unless you configure Page subscriptions in the App Dashboard and subscribe to that field.

#### Sample Request

```
curl -i -X POST \
  "https://graph.facebook.com/v25.0/1755847768034402/subscribed_apps?subscribed_fields=feed&access_token=EAAFB..."
```

##### Sample Response

```
{
  "success": true
}
```

## Common Uses

### Capture Story Insights

If you subscribe to the `story_insights` field, we send your endpoint a webhook notification containing user interaction metrics on a story, after the story has expired.

#### Sample Story Insights Payload

```
[
  {
    "entry": [
      {
        "changes": [
          {
            "field": "story_insights",
            "value": {
              "media_id": "18023345989012587",
              "exits": 1,
              "replies": 0,
              "reach": 17,
              "taps_forward": 12,
              "taps_back": 0,
              "impressions": 28
            }
          }
        ],
        "id": "17841405309211844",  // Instagram Business or Creator Account ID
        "time": 1547687043
      }
    ],
    "object": "instagram"
  }
]
```

### Reply to Comment @Mentions

If you subscribe to the `mentions` field, we send your endpoint a webhook notification whenever an Instagram user @mentions an Instagram Business or Creator Account in a comment or caption.

For example, here's a sample comment webhook notification payload sent for an Instagram Business Account (`17841405726653026`):

#### Sample Comment @Mention Payload

```
[
  {
    "entry": [
      {
        "changes": [
          {
            "field": "mentions",
            "value": {
              "comment_id": "17894227972186120",  // ID of the comment in which your app user's Instagram professional account was mentioned
              "media_id": "17918195224117851"     // ID of the media the Instagram user commented on
            }
          }
        ],
        "id": "17841405726653026",   // ID of your app user's Instagram professional account
        "time": 1520622968           // Time the notification was sent
      }
    ],
    "object": "instagram"
  }
]
```

### Get the Comment's Contents

To get the comment's contents, use the `comment_id` property to query the [`GET /{ig-user-id}/mentioned_comment`](/docs/instagram-api/reference/ig-user/mentioned_comment) edge:

#### Sample Query

```
GET https://graph.facebook.com/17841405726653026
  ?fields=mentioned_comment.comment_id(17894227972186120)
```

#### Sample Response

```
{
  "mentioned_comment": {
    "timestamp": "2018-03-20T00:05:29+0000",
    "text": "@bluebottle challenge?",
    "id": "17894227972186120"
  },
  "id": "17841405726653026"
}
```

### Parse the Payload and Respond

When you get the response, parse the payload for the `text` property to determine if you want to respond to the comment. To respond, use the webhook notification payload's `caption_id` and `media_id` property values to query the [`POST /{ig-user-id}/mentions`](/docs/instagram-api/reference/ig-user/mentions) endpoint:

#### Sample Query

```
curl -i -X POST \
  -d "comment_id=17894227972186120" \
  -d "media_id=17918195224117851" \
  -d "message=Challenge%20accepted!" \
  -d "access_token={access-token}" \
  "https://graph.facebook.com/17841405726653026/mentions"
```

#### Sample Response

```
{
  "id": "17911496353086895"
}
```

### Reply to Caption @Mentions

If you subscribe to the `mentions` field, we send your endpoint a webhook notification whenever a user @mentions an Instagram Business or Creator Account in a comment or caption on a media object not owned by the Business or Creator.

For example, here's a sample caption @mention webhook notification sent for an Instagram Business Account (`17841405726653026`):

#### Sample Caption @Mention Webhook Notification

```
[
  {
    "entry": [
      {
        "changes": [
          {
            "field": "mentions",
            "value": {
              "media_id": "17918195224117851"   // ID of the media where your app user's Instagram professional account was mentioned
            }
          }
        ],
        "id": "17841405726653026",   // ID of your app user's Instagram professional account
        "time": 1520622968           // The time Meta sent the notification
      }
    ],
    "object": "instagram"
  }
]
```

### Get the Caption's Contents

To get the caption's contents, use the `media_id` property to query the [`GET /{ig-user-id}/mentioned_media`](/docs/instagram-api/reference/ig-user/mentioned_media) edge:

#### Sample Query

```
GET https://graph.facebook.com/17841405726653026
  ?fields=mentioned_media.media_id(17918195224117851){caption,media_type}
```

#### Sample Response

```
{
  "mentioned_media": {
    "caption": "@bluebottle There can be only one!",
    "media_type": "IMAGE",
    "id": "17918195224117851"
  },
  "id": "17841405726653026"
}
```

### Parse the Payload and Respond

When you get the response, parse the payload for the `caption` property to determine if you want to respond to the comment. To respond, use the webhook `media_id` property to query the [`POST /{ig-user-id}/mentions`](/docs/instagram-api/reference/ig-user/mentions) edge:

#### Sample Query

```
curl -i -X POST \
  -d "media_id=17918195224117851" \
  -d "message=MacLeod%20agrees!" \
  -d "access_token={access-token}" \
  "https://graph.facebook.com/17841405726653026/mentions"
```

#### Sample Response

```
{
  "id": "17911496353086895"
}
```
