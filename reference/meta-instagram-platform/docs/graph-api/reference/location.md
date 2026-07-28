Graph API Version

[v25.0](#)

# Location

Represents a location.

## Reading

Get information about a location.

### Requirements

The [Page Public Content Access feature](https://developers.facebook.com/docs/apps/review/feature/#reference-PAGES_ACCESS) is required to scrape the LocationNode data of public pages.

#### Sample Request

```
curl -i -X GET \
 "https://graph.facebook.com/{graph-api-version}/{location-id}&access_token={user-access-token}"
```

#### Sample Response

```
{
  "name": "{city}, {state}",
  "id": "{location-id}"
}
```

## Get User Location Information

### Requirements

The [`user_location` permission](https://developers.facebook.com/docs/apps/review/login-permissions#user-location) is required.

#### Sample Request

```
curl -i -X GET \
  "https://graph.facebook.com/{graph-api-version}/{user-id}?
    fields=location{location{city,state,region_id}}&access_token={user-access-token}"
```

#### Sample Response

```
{
  "location": {
    "location": {
      "city": "San Jose",
      "state": "CA",
      "region_id": 3847
    },
    "id": "111948542155151"   //location-id
  },
  "id": "{user-id}"
}
```

## Get Page Location Information

### Requirements

The [`manage_pages` permission](https://developers.facebook.com/docs/apps/review/login-permissions#manage-pages) is required.

**Sample code of a Page location**

```
curl -i -X GET \
 "https://graph.facebook.com/{graph-api-version}/{page-id}?fields=location&access_token={page-access-token}"
```

#### Sample Response

```
{
  "location": {
    "city": "Menlo Park",
    "country": "United States",
    "latitude": 37.4786342,
    "located_in": "166793820034304",
    "longitude": -122.163581,
    "state": "CA",
    "street": "1 Hacker Way",
    "zip": "94025"
  },
  "id": "{page-id}"
}
```

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=...%3Ffields%3D%257Bfieldname_of_type_Location%257D&version=v25.0)

```
GET v25.0/...?fields={fieldname_of_type_Location} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '...?fields={fieldname_of_type_Location}',
    '{access-token}'
  );
} catch(Facebook\Exceptions\FacebookResponseException $e) {
  echo 'Graph returned an error: ' . $e->getMessage();
  exit;
} catch(Facebook\Exceptions\FacebookSDKException $e) {
  echo 'Facebook SDK returned an error: ' . $e->getMessage();
  exit;
}
$graphNode = $response->getGraphNode();
/* handle the result */
```

```
/* make the API call */
FB.api(
    "...?fields={fieldname_of_type_Location}",
    function (response) {
      if (response && !response.error) {
        /* handle the result */
      }
    }
);
```

```
/* make the API call */
new GraphRequest(
    AccessToken.getCurrentAccessToken(),
    "...?fields={fieldname_of_type_Location}",
    null,
    HttpMethod.GET,
    new GraphRequest.Callback() {
        public void onCompleted(GraphResponse response) {
            /* handle the result */
        }
    }
).executeAsync();
```

```
/* make the API call */
FBSDKGraphRequest *request = [[FBSDKGraphRequest alloc]
                               initWithGraphPath:@"...?fields={fieldname_of_type_Location}"
                                      parameters:params
                                      HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

If you want to learn how to use the Graph API, read our [Using Graph API guide](/docs/graph-api/using-graph-api/).

### Parameters

This endpoint doesn't have any parameters.

### Fields

| Field | Description |
| --- | --- |
| `city`  string | City  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `city_id`  unsigned int32 | City ID. Any city identified is also a city you can use for targeting ads. |
| `country`  string | Country  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `country_code`  string | Country code |
| `latitude`  float | Latitude  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `located_in`  id | The parent location if this location is located within another location  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `longitude`  float | Longitude  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `name`  string | Name  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `region`  string | Region |
| `region_id`  unsigned int32 | Region ID. Specifies a geographic region, such as California. An identified region is the same as one you can use to target ads. |
| `state`  string | State  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `street`  string | Street  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `zip`  string | Zip code  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

## Creating

You can make a POST request to `locations` edge from the following paths:

* [`/{page_id}/locations`](/docs/graph-api/reference/page/locations/)

When posting to this edge, a [Location](/docs/graph-api/reference/location/) will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `always_open`  boolean | Indicates whether this location is always open |
| `delivery_and_pickup_option_info`  array<string> | Specify upto 3 delivery/pickup URLs |
| `differently_open_offerings`  JSON object {enum {ONLINE\_SERVICES, DELIVERY, PICKUP, OTHER} : boolean} | A mapping of potential business offerings to true / false. Intended to be used / displayed when temporary\_status = "differently\_open" in order to express that the business is still operating in this capacity, such as a restaurant offering takeout. |
| `hours`  dictionary { string : <> } | Hours for this store. Please see the format for [hours in our page documentation](/docs/graph-api/reference/page) for examples |
| `ignore_warnings`  boolean | Whether to disable any warnings (not errors) that result from this API call, such as `latitude` and `longitude` not matching street address |
| `location`  Object | This defines the location for this page. This is required if the Page referenced by the `location_page_id` doesn't have a valid value for the field. The dictionary must include the keys `street` (street address), and either `city_id` or all of `city`, `state`, and `country` (but `state` is optional if the address is not in the U.S.). The `zip` is required for addresses in countries with postal codes. If Facebook isn't able to geocode the address, you must also include `latitude` and `longitude`. |
| `street`  string |  |
| `city`  string |  |
| `state`  string |  |
| `country`  string |  |
| `zip`  string |  |
| `city_id`  city id |  |
| `latitude`  float |  |
| `longitude`  float |  |
| `location_page_id`  numeric string | The ID of the Facebook Page you would like to add or update as a location |
| `old_store_number`  int64 | Old store number. Used when you want to change the store number for a location |
| `page_username`  string | Vanity URL for this location. This has to be an unused vanity URL. You should check by querying `/{page-username}` and looking for existing objects with this name |
| `permanently_closed`  boolean | Is this location permanently closed? |
| `phone`  string | Phone number for this location. This is required if the Page referenced by the `location_page_id` doesn't have a valid `phone`. |
| `pickup_options`  array<enum {CURBSIDE, IN\_STORE, OTHER}> | List of pickup options available at this Page's store location |
| `place_topics`  list<numeric string> | Place topics for this location. This is required if the Page referenced by the `location_page_id` doesn't have a valid `place_topic`. Use an array of IDs sourced from the [placetopic search endpoint](/docs/graph-api/using-graph-api#search) |
| `price_range`  string | Price range of the business, such as a restaurant or salon. Values can be one of `$`, `$$`, `$$$`, `$$$$`, `Not Applicable`, or null if the value is not set. |
| `recommendation_action`  enum {ACCEPT\_NEW, ACCEPT\_CLOSED, REJECT\_NEW, REJECT\_CLOSED} | recommendation\_action |
| `recommendation_ds`  string | recommendation\_ds |
| `recommendation_store_id`  int64 | recommendation\_store\_id |
| `store_code`  string | The store code. An arbitrary, alphanumeric, developer-defined ID for this location, usually used to link back to an internal database of locations |
| `store_location_descriptor`  string | Location descriptor for this store. This will appear after the Page name and should only be used if the location has a special location that's not clear from its city or street address. e.g. if it's inside a shopping mall or if it's best identified by its neighborhood |
| `store_name`  string | The store name |
| `store_number`  int64 | An arbitrary, developer-defined ID for this location, usually used to link back to an internal database of locations  Required |
| `temporary_status`  enum {DIFFERENTLY\_OPEN, TEMPORARILY\_CLOSED, OPERATING\_AS\_USUAL, NO\_DATA} | Indicates whether the business corresponding to this Page is temporarily closed or operating in a different-than-usual capacity |
| `type`  string | store recommendation type for logging purpose |
| `website`  URI | The URL of the location's website |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node represented by `id` in the return type.

Struct {

`id`: numeric string,

}

### Error Codes

| Error | Description |
| --- | --- |
| 371 | Invalid Page location update |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |
| 100 | Invalid parameter |
| 200 | Permissions error |
| 102 | Session key invalid or no longer valid |
| 80001 | There have been too many calls to this Page account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |
| 160 | Invalid geolocation type |
| 190 | Invalid OAuth 2.0 Access Token |

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.
