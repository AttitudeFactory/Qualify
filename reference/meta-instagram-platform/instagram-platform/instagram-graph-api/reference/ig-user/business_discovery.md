# IG User Business Discovery



Allows you to get data about other Instagram Business or Creator [IG Users](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user).

Available for the Instagram API with Facebook Login.

## Creating

This operation is not supported.

## Reading

**`GET /<IG_USER_ID>?fields=business_discovery.username(<USERNAME>)`**

Returns data about another Instagram Business or Creator [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user). Perform this request on the Instagram Business or Creator [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) who is making the query, and identify the targeted business with the `username` parameter.

### Limitations

Data about age-gated Instagram Business [IG Users](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) will not be returned.

### Query String Parameters

- `<USERNAME>` (required) — The username of the Instagram Business or Creator [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) you want to get data about.

### Permissions

A Facebook User [access token](https://developers.facebook.com/documentation/instagram-platform/overview#authentication) with the following permissions:

- `instagram_basic`
- `instagram_manage_insights`
- `pages_read_engagement`

If the token is from a User whose **Page role was granted via the Business Manager**, one of the following permissions is also required:

- `ads_management`
- `ads_read`

### Field Expansion

You can use field expansion get public fields on the targeted [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user). Refer to the [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) reference for a list of public fields.

### Sample Request with Field Expansion

Getting data about the Instagram Business [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) "Blue Bottle Coffee" and using field expansion to request its followers and media counts.

```
GET graph.facebook.com
  /17841405309211844
    ?fields=business_discovery.username(bluebottle){followers_count,media_count}
```

### Sample Response

```
{
  "business_discovery": {
    "followers_count": 267788,
    "media_count": 1205,
    "id": "17841401441775531"
  },
  "id": "17841405309211844"
}
```

### Accessing Edges with Field Expansion

You can also use field expansion to access the `/media` edge on the targeted [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) and specify the fields and metrics that should be returned for each [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) object. Refer to the [Media node reference](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) for a list of public fields.

### Sample Request with Edge

```
GET graph.facebook.com
  /17841405309211844
    ?fields=business_discovery.username(bluebottle){followers_count,media_count,media}
```

### Sample Response with Edge

```
{
  "business_discovery": {
    "followers_count": 267788,
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
        {
          "id": "17911489846004508"
        }
      ],
    },
    "id": "17841401441775531"
  },
  "id": "17841405309211844"
}
```

### Pagination

The `/media` edge supports [cursor-based pagination](https://developers.facebook.com/docs/graph-api/using-graph-api#paging), so when accessing it via field expansion, the response will include `before` and `after` cursors if the response contains multiple pages of data. Unlike standard cursor-based pagination, however, the response will not include `previous` or `next` fields, so you will have to use the `before` and `after` cursors to construct `previous` and `next` query strings manually in order to page through the returned data set.

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

## Updating

This operation is not supported.

## Deleting

This operation is not supported.
