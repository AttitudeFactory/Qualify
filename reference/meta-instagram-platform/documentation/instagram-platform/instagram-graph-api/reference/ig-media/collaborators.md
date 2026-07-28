# Collaborators



Represents a list of users who are added as collaborators on an IG Media object.

Available for the Instagram API with Facebook Login.

## Creating

This operation is not supported.

## Reading

Get a list of Instagram users as collaborators and their invitation status on an IG Media object.

**`GET /&lt;IG_MEDIA_ID&gt;`**

### Limitations

* Up to 5 Instagram accounts can be added as collaborators
* Only IG users who have enabled collaborator tagging will be returned in the response
* Collaborators tagging supports Feed image, Reels and Carousel, Stories is not supported

### Requirements

| Type | Description |
| --- | --- |
| [Access Tokens](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) | [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) – User must have created the IG Media object |
| [Permissions](https://developers.facebook.com/docs/permissions) | `instagram_basic`  &lt;br&gt;`pages_read_engagement`  &lt;br&gt;&lt;br&gt;If the app user was granted a role on the Page via the Business Manager, you also need one of the following:&lt;br&gt;&lt;br&gt;`ads_management`  &lt;br&gt;`ads_read` |

### Request syntax

```curl
GET https://graph.facebook.com/&lt;API_VERSION&gt;/&lt;IG_MEDIA_ID&gt;/collaborators&amp;&lt;USER_ACCESS_TOKEN&gt;
```

### Sample Response

```json
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;id&quot;: &quot;90010775360791&quot;,
      &quot;username&quot;: &quot;realtest1&quot;,
      &quot;invite_status&quot;: &quot;Accpeted&quot;
    &#125;,
    &#123;
      &quot;id&quot;: &quot;17841449208283139&quot;,
      &quot;username&quot;: &quot;realtest2&quot;,
      &quot;invite_status&quot;: &quot;Pending&quot;
    &#125;
  ]
&#125;
```

### Path Parameters

| Placeholder | Value |
| --- | --- |
| `&lt;API_VERSION&gt;` | API [version](https://developers.facebook.com/docs/graph-api/guides/versioning). |
| `&lt;IG_MEDIA_ID&gt;` | **Required.** The ID for your app user&#039;s Instagram media. |

### Query String Parameters

| Key | Placeholder | Value |
| --- | --- | --- |
| `access_token` | `&lt;USER_ACCESS_TOKEN&gt;` | **Required.** Your app user&#039;s [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) access token. |

### Response fields

| Field Name | Description |
| --- | --- |
| `id` | The App-scoped ID for the Instagram account of the potential collaborator |
| `invite_status` | The status for the invitation sent to a potential collaborator. Can be one of the following:&lt;br&gt;&lt;br&gt;* `Accepted`&lt;br&gt;* `Pending` |
| `username` | Instagram profile username for the potential collaborator |

## Updating

This operation is not supported.

## Deleting

This operation is not supported.
