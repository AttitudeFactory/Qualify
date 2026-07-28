Graph API Version

[v25.0](#)

# Permissions (`permissions`)

Category of updates relating to a user's granting or revoking a permission to your app

## `bookmarked`

Whether the user has added or removed the app bookmark

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `verb`  enum | Whether it is added or removed. |

## `connected`

Whether the user is connected or disconnected from the app

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `verb`  enum | Whether user is connected or disconnected. |

## `public_search`

Whether the user has granted the public\_search permission

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `verb`  enum | Whether it is granted or revoked. |

## `social_ads`

Whether the user has granted the social\_ads permission

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `verb`  enum | Whether it is granted or revoked. |
