Graph API Version

[v25.0](#)

# Application App Indexing

## Reading

You can't perform this operation on this endpoint.

## Creating

You can make a POST request to `app_indexing` edge from the following paths:

* [`/{application_id}/app_indexing`](/docs/graph-api/reference/application/app_indexing/)

When posting to this edge, an [Application](/docs/graph-api/reference/application/) will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `app_version`  string | The version of the app being indexed  Required |
| `device_session_id`  string | Device session id of the uploading device |
| `extra_info`  string | Extra information about the app index |
| `platform`  enum {ANDROID, IOS} | The platform of the app being indexed  Required |
| `request_type`  enum {APP\_INDEXING, PLUGIN, BUTTON\_SAMPLING} | Default value: `"APP_INDEXING"`  Type of the app indexing request |
| `tree`  JSON object | The UI component tree of the app  Required |
| `screenname`  string |  |
| `screenshot`  string |  |
| `view`  list<JSON encoded app UI component> | Required |

### Return Type

Struct {

`success`: bool,

`is_app_indexing_enabled`: bool,

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.
