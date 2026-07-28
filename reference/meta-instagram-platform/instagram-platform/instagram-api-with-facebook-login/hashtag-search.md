# Hashtag Search



Find public IG Media that has been tagged with specific hashtags.

## Limitations

- You can query a maximum of 30 unique hashtags on behalf of an Instagram Business or Creator Account within a rolling, 7 day period. Once you query a hashtag, it will [count against this limit](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/recently_searched_hashtags) for 7 days. Subsequent queries on the same hashtag within this time frame will not count against your limit, and will not reset its initial query 7 day timer.
- You cannot comment on hashtagged media objects discovered through the API.
- Hashtags on Stories are not supported.
- Emojis in hashtag queries are not supported.
- The API will return a generic error for any requests that include hashtags that we have deemed sensitive or offensive.

## Requirements

In order to use this API, you must undergo [App Review](https://developers.facebook.com/docs/apps/review) and request approval for:

- the [`Instagram Public Content Access`](https://developers.facebook.com/docs/apps/review/feature#reference-INSTAGRAM_PUBLIC_CONTENT_ACCESS) feature
- the [`instagram_basic`](https://developers.facebook.com/docs/facebook-login/permissions#reference-instagram_basic) permission

## Endpoints

The Hashtag Search API consists of the following nodes and edges:

- [`GET /ig_hashtag_search`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-hashtag-search#reading) — to get a specific hashtag's node ID
- [`GET /{ig-hashtag-id}`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-hashtag#reading) — to get data about a hashtag
- [`GET /{ig-hashtag-id}/top_media`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-hashtag/top-media#reading) — to get the most popular photos and videos that have a specific hashtag
- [`GET /{ig-hashtag-id}/recent_media`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-hashtag/recent-media#reading) — to get the most recently published photos and videos that have a specific hashtag
- [`GET /{ig-user-id}/recently_searched_hashtags`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/recently_searched_hashtags) — to determine the unique hashtags an Instagram Business or Creator Account has searched for in the current week

Refer to each endpoint's reference documentation for supported fields, parameters, and usage requirements.

## Common Uses

### Getting Media Tagged With A Hashtag

To get all of the photos and videos that have a specific hashtag, first use the `/ig_hashtag_search` endpoint and include the hashtag and ID of the Instagram Business or Creator Account making the query. For example, if the query is being made on behalf of the Instagram Business Account with the ID `17841405309211844`, you could get the ID for the "#coke" hashtag by performing the following query:

```
GET graph.facebook.com/ig_hashtag_search
  ?user_id=17841405309211844
  &q=coke
```

This will return the ID for the “#Coke” hashtag node:

```
{
  "id" : "17873440459141021"
}
```

Now that you have the hashtag ID (`17873440459141021`), you can query its `/top_media` or `/recent_media` edge and include the Business Account ID to get a collection of media objects that have the “#coke” hashtag. For example:

```
GET graph.facebook.com/17873440459141021/recent_media
  ?user_id=17841405309211844
```

This would return a response that looks like this:

```
{
  "data": [
    {
      "id": "17880997618081620"
    },
    {
      "id": "17871527143187462"
    },
    {
      "id": "17896450804038745"
    }
  ]
}
```
