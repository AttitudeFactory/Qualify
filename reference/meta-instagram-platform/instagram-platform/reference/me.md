# Me



This is a special endpoint that examines the Instagram User Access Token included in the request, determines the ID of the Instagram user who granted the token, and uses the ID to query the User endpoint.

## Creating

This operation is not supported.

## Reading

**`GET /me`**

Get fields and edges on the User whose Instagram User Access Token is being used in the query. This endpoint translates to `GET /{user-id}`, based on the User ID identified by the access token used in the query.

### Request Syntax

```
GET https://graph.instagram.com/v25.0/me
  ?fields={fields}
  &access_token={access-token}
```

Refer to the User node reference for requirements and usage details.

## Updating

This operation is not supported.

## Deleting

This operation is not supported.
