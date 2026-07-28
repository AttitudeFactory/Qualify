Graph API Version

[v25.0](#)

# Video Thumbnails

Represents a collection of
[VideoThumbnails
![](https://scontent-eze1-2.xx.fbcdn.net/v/t39.2365-6/310307727_3347317042262105_1088877051262827250_n.png?_nc_cat=107&ccb=1-7&_nc_sid=e280be&_nc_ohc=ML3XjuFMKyAQ7kNvwGv0co8&_nc_oc=Adoopxmt812yNn48i7SLLYOLz6sAWTzD5RjX9oj83GHKOgt9iiB8HRd7SjpITEOTf98&_nc_zt=14&_nc_ht=scontent-eze1-2.xx&_nc_gid=-MkfOyUSpHbySI8sx9ybhw&_nc_ss=7b20f&oh=00_AQBtvY2X_ZJOvJ5aVRFWdk13jyMOB0-tFUHvligmHrYs8g&oe=6A7D3EA2)](/docs/graph-api/reference/video-thumbnail)
on a
[Video
![](https://scontent-eze1-2.xx.fbcdn.net/v/t39.2365-6/310307727_3347317042262105_1088877051262827250_n.png?_nc_cat=107&ccb=1-7&_nc_sid=e280be&_nc_ohc=ML3XjuFMKyAQ7kNvwGv0co8&_nc_oc=Adoopxmt812yNn48i7SLLYOLz6sAWTzD5RjX9oj83GHKOgt9iiB8HRd7SjpITEOTf98&_nc_zt=14&_nc_ht=scontent-eze1-2.xx&_nc_gid=-MkfOyUSpHbySI8sx9ybhw&_nc_ss=7b20f&oh=00_AQBtvY2X_ZJOvJ5aVRFWdk13jyMOB0-tFUHvligmHrYs8g&oe=6A7D3EA2)](/docs/graph-api/reference/video)

## Reading

Get a list of [VideoThumbnails](/docs/graph-api/reference/video-thumbnail/) on a [Video](/docs/graph-api/reference/video/).

### Requirements

Type | Requirement || [Access Tokens](/docs/facebook-login/access-tokens) | App or Page |
| [Permissions](/docs/permissions/reference#p) | `pages_read_engagement`, `pages_show_list` |

### Examples

```
curl -X GET "https://graph.facebook.com/v25.0/video-id/thumbnails?access_token=page_access_token"
```

On success your app receives a list of VideoThumbnail objects for the video.

```
{
"id": "video-id-1",
"height": 1280,
"scale": 1,
"uri": "url-for-video-1",
"width": 720,
"is_preferred": false
},
{
"id": "video-id-2",
"height": 1280,
"scale": 1,
"uri": "url-for-video-2",
"width": 720,
"is_preferred": false
},
...
```

### Parameters

This endpoint doesn't have any parameters.

### Fields

Reading from this edge will return a JSON formatted result:

```
{
    "data": [],
    "paging": {}
}
```

#### `data`

A list of [VideoThumbnail](/docs/graph-api/reference/video-thumbnail/) nodes.

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

### Error Codes

| Error | Description |
| --- | --- |
| 190 | Invalid OAuth 2.0 Access Token |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |
| 100 | Invalid parameter |
| 283 | That action requires the extended permission pages\_read\_engagement and/or pages\_read\_user\_content and/or pages\_manage\_ads and/or pages\_manage\_metadata |
| 104 | Incorrect signature |
| 200 | Permissions error |

## Creating

You can make a POST request to `thumbnails` edge from the following paths:

* [`/{video_id}/thumbnails`](/docs/graph-api/reference/video/thumbnails/)

When posting to this edge, a [VideoThumbnail](/docs/graph-api/reference/video-thumbnail/) will be created.

### Limitations

* Maximum thumbnail file size 10MB.
* Thumbnails can only be created on [Videos](/docs/graph-api/reference/video/) that have been associated with a [Page](/docs/graph-api/reference/page/).
* We recommend that you use thumbnails with the same aspect ratio as the video.

### Requirements

Type | Requirement || [Access Tokens](/docs/facebook-login/access-tokens) | App or Page |
| [Permissions](/docs/permissions/reference#p) | `pages_read_user_content`, `pages_manage_engagement`, `pages_show_list` |

### Examples

```
curl -X POST "https://graph.facebook.com/v25.0/video-id/thumbnails
   ?access_token=page_access_token
   &is_preferred=true
   &source=@ThumbnailSample1.jpg"
```

On success your app receives a list of VideoThumbnail objects for the video.

```
{
  "success": true
}
```

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `is_preferred`  boolean | Default value: `false`  Set to `true` if this thumbnail is the preferred thumbnail to be shown for this video |
| `source`  image | The source for the thumbnail, an image file  Required |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node to which you POSTed.

Struct {

`success`: bool,

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 200 | Permissions error |

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.
