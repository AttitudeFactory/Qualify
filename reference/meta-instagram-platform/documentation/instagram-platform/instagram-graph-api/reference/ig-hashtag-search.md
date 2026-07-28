# IG Hashtag Search



This root edge allows you to get [IG Hashtag](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-hashtag) IDs.

Available for the Instagram API with Facebook Login.

## Creating

This operation is not supported.

## Reading

### Getting a Hashtag ID

`GET /ig_hashtag_search?user_id=&lt;USER_ID&gt;&amp;q=&lt;QUERY_STRING&gt;`

Returns the ID of an [IG Hashtag](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-hashtag). IDs are both static and global (i.e, the ID for `#bluebottle` will always be `17843857450040591` for all apps and all app users).

#### Query String Parameters

- `&lt;USER_ID&gt;` (required) — The ID of the [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) performing the request.
- `&lt;QUERY_STRING&gt;` (required) — The hashtag name to query.

#### Limitations

- You can query a maximum of 30 unique hashtags [within a 7 day period](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/recently_searched_hashtags).
- The API will return a generic error for any queries that include hashtags that we have deemed sensitive or offensive.

**Requirements**

| Type | Description |
| --- | --- |
| [Features](https://developers.facebook.com/docs/apps/review/feature) | [`Instagram Public Content Access`](https://developers.facebook.com/docs/apps/review/feature#reference-INSTAGRAM_PUBLIC_CONTENT_ACCESS) |
| [Permissions](https://developers.facebook.com/docs/apps/review/login-permissions) | [`instagram_basic`](https://developers.facebook.com/docs/facebook-login/permissions#reference-instagram_basic)&lt;br&gt;&lt;br&gt;If the token is from a User whose Page role was granted via the Business Manager, one of the following permissions is also required: `ads_management`, `business_management`, or `pages_read_engagement`. |
| [Tokens](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) | A User access token of a Facebook User who has been [approved for tasks on the connected Facebook Page](https://developers.facebook.com/documentation/instagram-platform/overview#access-tokens). |

#### Sample Request

```curl
curl -X GET \
 &quot;https://graph.facebook.com/v25.0/ig_hashtag_search?user_id=17841405309211844&amp;q=bluebottle&amp;access_token=&#123;access-token&#125;&quot;
```

#### Sample Response

```
&#123;
    &quot;data&quot;: [
        &#123;
            &quot;id&quot;: &quot;17843857450040591&quot;
        &#125;
    ]
&#125;
```

## Updating

This operation is not supported.

## Deleting

This operation is not supported.
