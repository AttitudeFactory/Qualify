# Business Discovery



You can use the Instagram API with Facebook Login to get basic metadata and metrics about other Instagram professional accounts.

### Limitations  

Data about age-gated Instagram  professional accounts will not be returned.

### Endpoints

The API consists of the following endpoints. Refer to the endpoint's reference documentation for parameter and permission requirements.

- [`GET /<YOUR_APP_USERS_IG_USER_ID>/business_discovery`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/business_discovery)

## Examples

### Get Follower & Media Count

This sample query shows how to get the number of followers and number of published media objects on the [Blue Bottle Coffee](https://www.instagram.com/bluebottle/) Instagram professional account. Notice that business discovery queries are performed on the app user's Instagram professional account ID (in this case, `17841405309211844`) with the username of the Instagram professional account that your app user is attempting to get data about (`bluebottle` in this example).

#### Sample Request
_Formatted for readability._

```curl
curl -i -X GET \
 "https://graph.facebook.com/v25.0/17841405309211844 \
  ?fields=business_discovery.username(bluebottle){followers_count,media_count} \
  &access_token=<YOUR_APP_USERS_INSTAGRAM_USER_ACCESS_TOKEN>"
```

#### Sample Response

```json
{
  "business_discovery": {
    "followers_count": 267793,
    "media_count": 1205,
    "id": "17841401441775531" // Blue Bottle's Instagram user ID
  },
  "id": "17841405309211844"  // Your app user's Instagram user ID
}
```

### Get Media

Since you can make nested requests by specifying an edge via the `fields` parameter, you can request the targeted professional account's `media` edge to get all of its published media objects.

#### Sample Request
_Formatted for readability._

```curl
curl -i -X GET \
 "https://graph.facebook.com/v25.0/17841405309211844 \
  ?fields=business_discovery.username(bluebottle){followers_count,media_count,media} \
  &access_token=<YOUR_APP_USERS_INSTAGRAM_USER_ACCESS_TOKEN>"
```

#### Sample Response

```json
{
  "business_discovery": {
    "followers_count": 267793,
    "media_count": 1205,
    "media": {
      "data": [
        {
          "id": "17858843269216389"
        },
        {
          "id": "17894036119131554"
        },
        {
          "id": "17894449363137701"
        },
        {
          "id": "17844278716241265"
        },
        ... // results truncated for brevity
      ],
    "id": "17841401441775531"
  },
  },
  "id": "17841405309211844"
}
```

### Get Basic Metrics on Media

You can use both nested requests and field expansion to get public fields for a Business or Creator Account's media objects. Note that this does not grant you permission to access media objects directly — performing a `GET` on any returned [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) will fail due to insufficient permissions.

For example, here's how to get the number of comments and likes for each of the media objects published by Blue Bottle Coffee:

**Warning:** Please note that `view_count` includes both paid and organic metrics

### Sample Request

```
GET graph.facebook.com
  /17841405309211844
    ?fields=business_discovery.username(bluebottle){media{comments_count,like_count,view_count}}
```

### Sample Response

```
{
  "business_discovery": {
    "media": {
      "data": [
        {
          "comments_count": 50,
          "like_count": 5837,
          "view_count": 7757,
          "id": "17858843269216389"
        },
        {
          "comments_count": 11,
          "like_count": 2997,
          "id": "17894036119131554"
        },
        {
          "comments_count": 28,
          "like_count": 3643,
          "id": "17894449363137701"
        },
        {
          "comments_count": 43,
          "like_count": 4943,
          "id": "17844278716241265"
        },
     ],
   },
   "id": "17841401441775531"
  },
  "id": "17841405976406927"
}
```
