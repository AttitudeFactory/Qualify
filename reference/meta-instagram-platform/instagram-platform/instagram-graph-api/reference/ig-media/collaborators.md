# Collaborators



Represents a list of users who are added as collaborators on an IG Media object.

Available for the Instagram API with Facebook Login.

## Creating

This operation is not supported.

## Reading

Get a list of Instagram users as collaborators and their invitation status on an IG Media object.

**`GET /<IG_MEDIA_ID>`**

### Limitations

* Up to 5 Instagram accounts can be added as collaborators
* Only IG users who have enabled collaborator tagging will be returned in the response
* Collaborators tagging supports Feed image, Reels and Carousel, Stories is not supported

### Requirements

| Type | Description |
| --- | --- |
| [Access Tokens](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) | [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) – User must have created the IG Media object |
| [Permissions](https://developers.facebook.com/docs/permissions) | `instagram_basic`  <br>`pages_read_engagement`  <br><br>If the app user was granted a role on the Page via the Business Manager, you also need one of the following:<br><br>`ads_management`  <br>`ads_read` |

### Request syntax

```curl
GET https://graph.facebook.com/<API_VERSION>/<IG_MEDIA_ID>/collaborators&<USER_ACCESS_TOKEN>
```

### Sample Response

```json
{
  "data": [
    {
      "id": "90010775360791",
      "username": "realtest1",
      "invite_status": "Accpeted"
    },
    {
      "id": "17841449208283139",
      "username": "realtest2",
      "invite_status": "Pending"
    }
  ]
}
```

### Path Parameters

| Placeholder | Value |
| --- | --- |
| `<API_VERSION>` | API [version](https://developers.facebook.com/docs/graph-api/guides/versioning). |
| `<IG_MEDIA_ID>` | **Required.** The ID for your app user's Instagram media. |

### Query String Parameters

| Key | Placeholder | Value |
| --- | --- | --- |
| `access_token` | `<USER_ACCESS_TOKEN>` | **Required.** Your app user's [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) access token. |

### Response fields

| Field Name | Description |
| --- | --- |
| `id` | The App-scoped ID for the Instagram account of the potential collaborator |
| `invite_status` | The status for the invitation sent to a potential collaborator. Can be one of the following:<br><br>* `Accepted`<br>* `Pending` |
| `username` | Instagram profile username for the potential collaborator |

## Updating

This operation is not supported.

## Deleting

This operation is not supported.
