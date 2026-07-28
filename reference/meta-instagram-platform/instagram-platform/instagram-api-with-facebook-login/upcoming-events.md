# Instagram Upcoming Events



This document explains how to manage Instagram events using the Instagram API with Facebook Login, covering creation, modification and retrieval of existing events.

In this document we use "Instagram User" and "Instagram Account" interchangeable; both represent your app user's Instagram professional account.

## Before You Start

You'll need the following:

* The `instagram_basic` permission
* The `instagram_manage_upcoming_events` permission
* The ID of the app user's Instagram professional account linked to a Business

### Limitations

* Only supports Instagram Professional accounts linked to a Business
* Currently only supports retrieval of events created via Ads Manager or this API
* Intended to facilitate the creation of reminder ads

## Create a New Event

To create a new event, send a `POST` request to the `/<IG_USER_ID>/upcoming_events` endpoint, where `<IG_USER_ID>` is the ID for your app user's Instagram professional account, including the following parameters:

* `title`
* `start_time`
* `notification_subtypes` (optional)
* `end_time` (optional)
* `notification_target_time` (optional)

### Request

*Formatted for readability. Make sure to replace placeholders with your own values.*

```
curl -X POST "https://graph.facebook.com/v25.0/<IG_USER_ID>/upcoming_events" \
  -F 'title="Season Premiere"' \
  -F 'start_time="2024-06-30T19:00:00+0000"' \
  -F 'notification_subtypes=["BEFORE_EVENT_1DAY", "BEFORE_EVENT_15MIN", "EVENT_START"]' \
  -F 'access_token=<ACCESS_TOKEN>'
```

On success, your app receives a JSON response containing the new event's ID.

```json
{
  "id": "<EVENT_ID>"
}
```

### Parameters

| Name | Description |
| --- | --- |
| `end_time`<br><br>ISO string | Optional. The event's end time.  <br>**Note:** Must not be set when setting `notification_target_time` to `"EVENT_END"`. |
| `notification_target_time`<br><br>string | Optional. A string value specifying the part of the event relative to which notifications will be sent. Supported values are `"EVENT_START"` or `"EVENT_END"`.<br><br>If not set in the request, defaults to `"EVENT_START"`. When set to `"EVENT_END"`, the `notification_subtypes` field must include the following three values in any order: `[“BEFORE_EVENT_2DAY”, “BEFORE_EVENT_1DAY”, “BEFORE_EVENT_1HOUR”]`.<br><br>Additionally, when set to `"EVENT_END"`, the event `end_date` must not be specified. |
| `notification_subtypes`<br><br>array of strings | Optional.<br>A comma-separated list of three values that describe when notifications will be sent to event subscribers relative to the event’s `start_time`.<br>If not set in the request, defaults to `"BEFORE_EVENT_1DAY"`, `"BEFORE_EVENT_15MIN"`, and `"EVENT_START"`.<br><br>If set without specifying `notification_target_time` or with `notification_target_time` set to `"EVENT_START"`, `"EVENT_START"` and `"BEFORE_EVENT_1DAY"` are required with one additional value. Possible additional values include:<br><br>* `"AFTER_EVENT_1DAY"`<br>* `"AFTER_EVENT_2DAY"`<br>* `"AFTER_EVENT_3DAY"`<br>* `"AFTER_EVENT_4DAY"`<br><br>* `"AFTER_EVENT_5DAY"`<br>* `"AFTER_EVENT_6DAY"`<br>* `"AFTER_EVENT_7DAY"`<br>* `"BEFORE_EVENT_15MIN"`<br><br>Order does not matter.<br><br>If `notification_target_time` is set to `"EVENT_END"`, the specified values here must be: `[“BEFORE_EVENT_2DAY”, “BEFORE_EVENT_1DAY”, “BEFORE_EVENT_1HOUR”]` |
| `start_time`<br><br>ISO string | **Required.** The event's start time. |
| `title`<br><br>string | **Required.** The event's title. |

## Retrieve an event

To retrieve details of an existing event, send a `GET` request to the `/<EVENT_ID>` endpoint.

### Request

*Formatted for readability. Make sure to replace placeholders with your own values.*

```curl
curl -X GET "https://graph.facebook.com/v25.0/<EVENT_ID>?access_token=<ACCESS_TOKEN>"
```

On success, your app receives a JSON response containing the ID, title , and start time for the event.

```json
{
  "id": "<EVENT_ID>"
  "title":"Updated Season Premier",
  "start_time":"2024-05-11T16:00:00+0000"
}
```

## Update an Existing Event

To update the details of an existing event, send a `POST` request to the `/<EVENT_ID>` and include one or more of the following parameters that you want to update:

* `title`
* `start_time`
* `notification_subtypes` (optional)
* `end_time` (optional)

### Example Request

*Formatted for readability. Make sure to replace placeholders with your own values.*

```curl
curl -X POST "https://graph.facebook.com/v25.0/<EVENT_ID>" \
     -F 'title="Season Premiere"' \
     -F 'start_time="2024-06-30T19:00:00+0000"' \
     -F 'notification_subtypes=["BEFORE_EVENT_1DAY", "BEFORE_EVENT_15MIN", "EVENT_START"]' \
     -F 'access_token=<ACCESS_TOKEN>'
```

On success, your app receives a JSON response containing the ID for the event.

```json
{
  "id": "<EVENT_ID>"
}
```

## Retrieve all Upcoming Events

To retrieve a list of all upcoming events, send a `GET` request to the `/<IG_USER_ID>/upcoming_events`.

### Request

*Formatted for readability. Make sure to replace placeholders with your own values.*

```curl
curl -X GET "https://graph.facebook.com/v25.0/<IG_USER_ID>/upcoming_events?access_token=<ACCESS_TOKEN>"
```

On success, your app receives a JSON response containing a list of all upcoming events with the ID, title, and start time for each.

```json
{
  "data": [
    {
      "id": "<EVENT_ID_1>,"
      "title":"<EVENT_TITLE_1>",
      "start_time":"2024-04-11T16:00:00+0000"
    },
    {
      "id": "<EVENT_ID_2>,"
      "title":"<EVENT_TITLE_2>",
      "start_time":"2024-04-18T16:00:00+0000"
    },
    {
      "id": "<EVENT_ID_3>,"
      "title":"<EVENT_TITLE_3>",
      "start_time":"2024-04-25T16:00:00+0000"
    },
  ]
}
```

## Next Steps

- Learn how to create
[Instagram Reminder Ads](https://developers.facebook.com/documentation/ads-commerce/instagram/marketing-api/guides/reminder-ads)
using Meta's Marketing API.

