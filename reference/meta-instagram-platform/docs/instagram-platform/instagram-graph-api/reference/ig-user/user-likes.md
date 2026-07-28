# User Likes

You can like and unlike Instagram Media (Feed, Reels, Carousel) and Comments (Comments, Replies) on behalf of an Instagram User.

## Like a Media or Comment

Publish a "Like" on an Instagram Media or Comment on behalf of an Instagram User.

**Note:** If the object was already liked by the Instagram User, the API has no effect.

**`POST /<IG_USER_ID>/likes`**

### Limitations

* Supports Feed Image, Reels and Carousel objects and their Comments/Replies.
* Stories is not supported.
* Burst rate limit: more than 50 requests in 5 seconds results in a 1-hour lockout for the Instagram User.
* Media and Comments from Private Accounts cannot be liked.

### Requirements

Type | Description || [Access Tokens](/docs/facebook-login/access-tokens#usertokens) | [User](/docs/facebook-login/access-tokens#usertokens) – The Instagram User on whose behalf the Like is being published. |
| [Permissions](/docs/permissions) | `instagram_basic`  `instagram_manage_engagement` |

**Note:** You can supply either `media_id` or `comment_id` as a query string parameter or in the request body — but not both parameters at the same time.

### Example Request – Like a Media (Query String)

```
curl -i -X POST "https://graph.facebook.com/v25.0/<IG_USER_ID>/likes?access_token=<USER_ACCESS_TOKEN>&media_id=<IG_MEDIA_ID>"
```

### Example Response

```
{
  "success": true
}
```

### Example Request – Like a Media (Request Body)

```
curl -i -X POST "https://graph.facebook.com/v25.0/<IG_USER_ID>/likes" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <USER-ACCESS-TOKEN>" \
  -d '{"media_id": "<IG_MEDIA_ID>"}'
```

### Example Response

```
{
  "success": true
}
```

### Example Request – Like a Comment (Query String)

```
curl -i -X POST "https://graph.facebook.com/v25.0/<IG_USER_ID>/likes?access_token=<USER_ACCESS_TOKEN>&comment_id=<IG_COMMENT_ID>"
```

### Example Response

```
{
  "success": true
}
```

### Example Request – Like a Comment (Request Body)

```
curl -i -X POST "https://graph.facebook.com/v25.0/<IG_USER_ID>/likes" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <USER-ACCESS-TOKEN>" \
  -d '{"comment_id": "<IG_COMMENT_ID>"}'
```

### Example Response

```
{
  "success": true
}
```

### Path Parameters

Placeholder | Value || `<API_VERSION>` | The API [version](/docs/graph-api/guides/versioning): `v25.0`. |
| `<IG_USER_ID>` *Required string* | The ID for your app user's Instagram User. |

### Query String Parameters

Key | Placeholder | Value || `access_token` *Required string* | `<USER_ACCESS_TOKEN>` | Your app user's [User](/docs/facebook-login/access-tokens/#usertokens) access token. |
| `media_id` *Optional string* | `<IG_MEDIA_ID>` | The ID of the target Instagram Media to like. Supply this parameter to like a Media object. |
| `comment_id` *Optional string* | `<IG_COMMENT_ID>` | The ID of the target Instagram Comment or Reply to like. Supply this parameter to like a Comment object. |

### Response Fields

Field Name | Description || `success` | Boolean flag to indicate whether the Like was published successfully. |

## Unlike a Media or Comment

Remove a "Like" from an Instagram Media or Comment on behalf of an Instagram User.

**Note:** If the object was not previously liked by the Instagram User, the API has no effect.

**`DELETE /<IG_USER_ID>/likes`**

### Limitations

* Supports Feed Image, Reels and Carousel objects and their Comments/Replies.
* Stories is not supported.
* Burst rate limit: more than 50 requests in 5 seconds results in a 1-hour lockout for the Instagram User.

### Requirements

Type | Description || [Access Tokens](/docs/facebook-login/access-tokens#usertokens) | [User](/docs/facebook-login/access-tokens#usertokens) – The Instagram User on whose behalf the Like is being removed. |
| [Permissions](/docs/permissions) | `instagram_basic`  `instagram_manage_engagement` |

**Note:** You can supply either `media_id` or `comment_id` as a query string parameter or in the request body — but not both parameters at the same time.

### Example Request – Unlike a Media (Query String)

```
curl -i -X DELETE "https://graph.facebook.com/v25.0/<IG_USER_ID>/likes?access_token=<USER_ACCESS_TOKEN>&media_id=<IG_MEDIA_ID>"
```

### Example Response

```
{
  "success": true
}
```

### Example Request – Unlike a Media (Request Body)

```
curl -i -X DELETE "https://graph.facebook.com/v25.0/<IG_USER_ID>/likes" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <USER-ACCESS-TOKEN>" \
  -d '{"media_id": "<IG_MEDIA_ID>"}'
```

### Example Response

```
{
  "success": true
}
```

### Example Request – Unlike a Comment (Query String)

```
curl -i -X DELETE "https://graph.facebook.com/v25.0/<IG_USER_ID>/likes?access_token=<USER_ACCESS_TOKEN>&comment_id=<IG_COMMENT_ID>"
```

### Example Response

```
{
  "success": true
}
```

### Example Request – Unlike a Comment (Request Body)

```
curl -i -X DELETE "https://graph.facebook.com/v25.0/<IG_USER_ID>/likes" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <USER-ACCESS-TOKEN>" \
  -d '{"comment_id": "<IG_COMMENT_ID>"}'
```

### Example Response

```
{
  "success": true
}
```

### Path Parameters

Placeholder | Value || `<API_VERSION>` | The API [version](/docs/graph-api/guides/versioning): `v25.0`. |
| `<IG_USER_ID>` *Required string* | The ID for your app user's Instagram User. |

### Query String Parameters

Key | Placeholder | Value || `access_token` *Required string* | `<USER_ACCESS_TOKEN>` | Your app user's [User](/docs/facebook-login/access-tokens/#usertokens) access token. |
| `media_id` *Optional string* | `<IG_MEDIA_ID>` | The ID of the target Instagram Media to unlike. Supply this parameter to unlike a Media object. |
| `comment_id` *Optional string* | `<IG_COMMENT_ID>` | The ID of the target Instagram Comment or Reply to unlike. Supply this parameter to unlike a Comment object. |

### Response Fields

Field Name | Description || `success` | Boolean flag to indicate whether the Unlike was performed successfully. |
