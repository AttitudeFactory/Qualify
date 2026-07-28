# Ad Preview



Preview your ad.

## Limitations

Only certain combinations of creatives and `ad_format` are supported:

- Link ad not connected to a page: `RIGHT_COLUMN_STANDARD`

- Page like ad: `RIGHT_COLUMN_STANDARD`, `DESKTOP_FEED_STANDARD`, `MOBILE_FEED_STANDARD`

- Event ad: `RIGHT_COLUMN_STANDARD`

- Page like ad: `RIGHT_COLUMN_STANDARD`

- Page post ad: `RIGHT_COLUMN_STANDARD`, `DESKTOP_FEED_STANDARD`, `MOBILE_FEED_STANDARD`, `INSTAGRAM_STANDARD`

- Desktop app ad: `DESKTOP_FEED_STANDARD`

- Mobile app install: `MOBILE_FEED_STANDARD`, `INSTAGRAM_STANDARD`, `MOBILE_BANNER`, `MOBILE_INTERSTITIAL`, `FACEBOOK_STORY_MOBILE`

If you use Page Post with a link to an app on the Google Play Store or on the Apple App Store, we override and import these fields:

- the `name` parameter of the Page Post will be overwritten with the name of the app from the Play Store/App Store.

- the thumbnail icon of the app associated with the Page Post will be imported from the Play Store/App Store.

`FACEBOOK_STORY_MOBILE` only supports single video and single image.

## Reading

Preview of the ad.

#### Example

### HTTP
```
GET /v25.0/&#123;ad-id&#125;/previews HTTP/1.1
Host: graph.facebook.com
```

### PHP SDK
```
/* PHP SDK v5.0.0 */
/* make the API call */
try &#123;
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb-&gt;get(
    &#039;/&#123;ad-id&#125;/previews&#039;,
    &#039;&#123;access-token&#125;&#039;
  );
&#125; catch(Facebook\Exceptions\FacebookResponseException $e) &#123;
  echo &#039;Graph returned an error: &#039; . $e-&gt;getMessage();
  exit;
&#125; catch(Facebook\Exceptions\FacebookSDKException $e) &#123;
  echo &#039;Facebook SDK returned an error: &#039; . $e-&gt;getMessage();
  exit;
&#125;
$graphNode = $response-&gt;getGraphNode();
/* handle the result */
```

### JavaScript SDK
```
/* make the API call */
FB.api(
    &quot;/&#123;ad-id&#125;/previews&quot;,
    function (response) &#123;
      if (response &amp;&amp; !response.error) &#123;
        /* handle the result */
      &#125;
    &#125;
);
```

### Android SDK
```
/* make the API call */
new GraphRequest(
    AccessToken.getCurrentAccessToken(),
    &quot;/&#123;ad-id&#125;/previews&quot;,
    null,
    HttpMethod.GET,
    new GraphRequest.Callback() &#123;
        public void onCompleted(GraphResponse response) &#123;
            /* handle the result */
        &#125;
    &#125;
).executeAsync();
```

### iOS SDK
```
/* make the API call */
FBSDKGraphRequest *request = [[FBSDKGraphRequest alloc]
                               initWithGraphPath:&#064;&quot;/&#123;ad-id&#125;/previews&quot;
                                      parameters:params
                                      HTTPMethod:&#064;&quot;GET&quot;];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) &#123;
    // Handle the result
&#125;];
```

Try it in [Graph API Explorer](https://developers.facebook.com/tools/explorer/?method=GET&amp;path=%7Bad-id%7D%2Fpreviews&amp;version=v25.0)

If you want to learn how to use the Graph API, read our [Using Graph API guide](https://developers.facebook.com/docs/graph-api/using-graph-api)

#### Parameters

| Parameter | Description |
| --- | --- |
| `ad_format`&lt;br&gt;&lt;br&gt;*enum&#123;AUDIENCE_NETWORK_INSTREAM_VIDEO, AUDIENCE_NETWORK_INSTREAM_VIDEO_MOBILE, AUDIENCE_NETWORK_OUTSTREAM_VIDEO, AUDIENCE_NETWORK_REWARDED_VIDEO, BIZ_DISCO_FEED_MOBILE, DESKTOP_FEED_STANDARD, FACEBOOK_IFU_REELS_MOBILE, FACEBOOK_PROFILE_FEED_DESKTOP, FACEBOOK_PROFILE_FEED_MOBILE, FACEBOOK_PROFILE_REELS_MOBILE, FACEBOOK_REELS_BANNER, FACEBOOK_REELS_BANNER_DESKTOP, FACEBOOK_REELS_BANNER_FEED_ANDROID, FACEBOOK_REELS_BANNER_FEED_ANDROID_LARGE, FACEBOOK_REELS_BANNER_FULLSCREEN_IOS, FACEBOOK_REELS_BANNER_FULLSCREEN_MOBILE, FACEBOOK_REELS_MOBILE, FACEBOOK_REELS_POSTLOOP, FACEBOOK_REELS_POSTLOOP_FEED, FACEBOOK_REELS_SIMILAR_PRODUCTS_MOBILE, FACEBOOK_REELS_STICKER, FACEBOOK_STORY_MOBILE, FACEBOOK_STORY_STICKER_MOBILE, INSTAGRAM_EXPLORE_CONTEXTUAL, INSTAGRAM_EXPLORE_GRID_HOME, INSTAGRAM_EXPLORE_IMMERSIVE, INSTAGRAM_FEED_WEB, INSTAGRAM_FEED_WEB_M_SITE, INSTAGRAM_LEAD_GEN_MULTI_SUBMIT_ADS, INSTAGRAM_PROFILE_FEED, INSTAGRAM_PROFILE_REELS, INSTAGRAM_REELS, INSTAGRAM_REELS_OVERLAY, INSTAGRAM_REELS_WEB, INSTAGRAM_REELS_WEB_M_SITE, INSTAGRAM_SEARCH_CHAIN, INSTAGRAM_SEARCH_GRID, INSTAGRAM_STANDARD, INSTAGRAM_STORY, INSTAGRAM_STORY_EFFECT_TRAY, INSTAGRAM_STORY_WEB, INSTAGRAM_STORY_WEB_M_SITE, INSTANT_ARTICLE_RECIRCULATION_AD, INSTANT_ARTICLE_STANDARD, INSTREAM_BANNER_DESKTOP, INSTREAM_BANNER_FEED_IOS, INSTREAM_BANNER_FULLSCREEN_IOS, INSTREAM_BANNER_FULLSCREEN_MOBILE, INSTREAM_BANNER_IMMERSIVE_MOBILE, INSTREAM_BANNER_MOBILE, INSTREAM_VIDEO_DESKTOP, INSTREAM_VIDEO_FULLSCREEN_IOS, INSTREAM_VIDEO_FULLSCREEN_MOBILE, INSTREAM_VIDEO_IMAGE, INSTREAM_VIDEO_IMMERSIVE_MOBILE, INSTREAM_VIDEO_MOBILE, JOB_BROWSER_DESKTOP, JOB_BROWSER_MOBILE, MARKETPLACE_MOBILE, MESSENGER_MOBILE_INBOX_MEDIA, MESSENGER_MOBILE_STORY_MEDIA, MOBILE_BANNER, MOBILE_FEED_BASIC, MOBILE_FEED_STANDARD, MOBILE_FULLWIDTH, MOBILE_INTERSTITIAL, MOBILE_MEDIUM_RECTANGLE, MOBILE_NATIVE, RIGHT_COLUMN_STANDARD, SUGGESTED_VIDEO_DESKTOP, SUGGESTED_VIDEO_FULLSCREEN_MOBILE, SUGGESTED_VIDEO_IMMERSIVE_MOBILE, SUGGESTED_VIDEO_MOBILE, WATCH_FEED_HOME, WATCH_FEED_MOBILE, WHATSAPP_STATUS_MEDIA&#125;* | Use this to select what placement on Facebook the ad preview should be for. The API returns an iframe, which is only valid for 24 hours.&lt;br&gt;&lt;br&gt;Ad formats for Facebook: `DESKTOP_FEED_STANDARD`, `FACEBOOK_STORY_MOBILE`, `INSTANT_ARTICLE_STANDARD`, `INSTREAM_VIDEO_DESKTOP`, `INSTREAM_VIDEO_MOBILE`, `MARKETPLACE_DESKTOP`,`MARKETPLACE_MOBILE`, `MOBILE_FEED_BASIC`, `MOBILE_FEED_STANDARD`, `RIGHT_COLUMN_STANDARD`, `SUGGESTED_VIDEO_DESKTOP`, `SUGGESTED_VIDEO_MOBILE`, `WATCH_FEED_MOBILE`, `FACEBOOK_REELS_BANNER`, `FACEBOOK_REELS_BANNER_DESKTOP`, `FACEBOOK_REELS_MOBILE`, `FACEBOOK_REELS_POSTLOOP`, `FACEBOOK_REELS_STICKER`, `FACEBOOK_STORY_STICKER_MOBILE`, `WATCH_FEED_HOME`.&lt;br&gt;&lt;br&gt;Ad formats for Instagram: `INSTAGRAM_STANDARD`, `INSTAGRAM_STORY`, `INSTAGRAM_EXPLORE_CONTEXTUAL`, `INSTAGRAM_EXPLORE_IMMERSIVE`, `INSTAGRAM_EXPLORE_GRID_HOME`, `INSTAGRAM_FEED_WEB`, `INSTAGRAM_FEED_WEB_M_SITE`, `INSTAGRAM_PROFILE_FEED`, `INSTAGRAM_REELS`, `INSTAGRAM_REELS_OVERLAY`, `INSTAGRAM_SEARCH_CHAIN`, `INSTAGRAM_SEARCH_GRID`, `INSTAGRAM_STORY_CAMERA_TRAY`, `INSTAGRAM_STORY_WEB`, `INSTAGRAM_STORY_WEB_M_SITE`. [Learn more about Instagram placement options](https://developers.facebook.com/documentation/ads-commerce/instagram/ads-api/guides/carousel-ads#adpreview).&lt;br&gt;&lt;br&gt;Ad formats for Messenger: `MESSENGER_MOBILE_INBOX_MEDIA`, `MESSENGER_MOBILE_STORY_MEDIA`.&lt;br&gt;&lt;br&gt;Ad formats for Audience Network: `AUDIENCE_NETWORK_INSTREAM_VIDEO`, `AUDIENCE_NETWORK_INSTREAM_VIDEO_MOBILE`, `AUDIENCE_NETWORK_OUTSTREAM_VIDEO`, `AUDIENCE_NETWORK_REWARDED_VIDEO`, `MOBILE_BANNER`, `MOBILE_FULLWIDTH`, `MOBILE_INTERSTITIAL`, `MOBILE_MEDIUM_RECTANGLE`, `MOBILE_NATIVE`.&lt;br&gt;&lt;br&gt;**[required]**&lt;br&gt; |
| `dynamic_asset_label`&lt;br&gt;&lt;br&gt;*string* | Provide a label for rendering specific variation of an asset customization ad&lt;br&gt; |
| `dynamic_creative_spec`&lt;br&gt;&lt;br&gt;*Object* | Dynamic creative spec for dynamic ads.&lt;br&gt;&lt;br&gt;**[supports emoji]**&lt;br&gt; |
| `dynamic_customization`&lt;br&gt;&lt;br&gt;*Object* | For dynamic ads in multiple languages, specify the customization to be applied to the ad&lt;br&gt; |
| `end_date`&lt;br&gt;&lt;br&gt;*datetime* | Provide an end date for trip&#039;s tag parameters in the creative. See [Template Tags](https://developers.facebook.com/documentation/ads-commerce/marketing-api/flight-ads/template-tags)&lt;br&gt; |
| `height`&lt;br&gt;&lt;br&gt;*int64* | Custom height of the resulting iframe, recommended at least 280 x 280 for the large right hand size height.&lt;br&gt;Note: the parameter affects only the size of the iframe containing the preview object. It has no affect on the actual size of the previewed ad.&lt;br&gt; |
| `place_page_id`&lt;br&gt;&lt;br&gt;*Page ID* | Place page ID to use when rendering a dynamic local ad preview&lt;br&gt; |
| `post`&lt;br&gt;&lt;br&gt;*Object* | Specs for a page post. This field is used when the creative field contains only a Page id as `object_id` in it. Not supported for `ad_format = RIGHT_COLUMN_STANDARD`&lt;br&gt;&lt;br&gt;&lt;br&gt;`link` *URL*&lt;br&gt;Destination URL of the ad&lt;br&gt;&lt;br&gt;**[required]**&lt;br&gt;&lt;br&gt;&lt;br&gt;`message` *UTF-8 string*&lt;br&gt;Post message&lt;br&gt;&lt;br&gt;**[supports emoji]**&lt;br&gt;&lt;br&gt;&lt;br&gt;`picture` *URL*&lt;br&gt;Image URL&lt;br&gt;&lt;br&gt;&lt;br&gt;`name` *UTF-8 encoded string*&lt;br&gt;Post name&lt;br&gt;&lt;br&gt;&lt;br&gt;`caption` *UTF-8 encoded string*&lt;br&gt;Post caption&lt;br&gt;&lt;br&gt;&lt;br&gt;`description` *UTF-8 encoded string*&lt;br&gt;Post description&lt;br&gt;&lt;br&gt;&lt;br&gt;`call_to_action` *Object*&lt;br&gt;Call to action&lt;br&gt;&lt;br&gt;**[supports emoji]**&lt;br&gt;&lt;br&gt;&lt;br&gt;`type` *enum&#123;BOOK_TRAVEL, CONTACT_US, DONATE, DONATE_NOW, DOWNLOAD, GET_DIRECTIONS, GO_LIVE, INTERESTED, LEARN_MORE, SEE_DETAILS, LIKE_PAGE, MESSAGE_PAGE, RAISE_MONEY, SAVE, SEND_TIP, SHOP_NOW, SIGN_UP, VIEW_INSTAGRAM_PROFILE, INSTAGRAM_MESSAGE, LOYALTY_LEARN_MORE, PURCHASE_GIFT_CARDS, PAY_TO_ACCESS, SEE_MORE, TRY_IN_CAMERA, WHATSAPP_LINK, GET_IN_TOUCH, TRY_NOW, ASK_A_QUESTION, START_A_CHAT, CHAT_NOW, ASK_US, CHAT_WITH_US, BOOK_NOW, CHECK_AVAILABILITY, ORDER_NOW, WHATSAPP_MESSAGE, GET_MOBILE_APP, INSTALL_MOBILE_APP, USE_MOBILE_APP, INSTALL_APP, USE_APP, PLAY_GAME, TRY_DEMO, WATCH_VIDEO, WATCH_MORE, OPEN_LINK, NO_BUTTON, LISTEN_MUSIC, MOBILE_DOWNLOAD, GET_OFFER, GET_OFFER_VIEW, BUY_NOW, BUY_TICKETS, UPDATE_APP, BET_NOW, ADD_TO_CART, SELL_NOW, GET_SHOWTIMES, LISTEN_NOW, GET_EVENT_TICKETS, REMIND_ME, SEARCH_MORE, PRE_REGISTER, SWIPE_UP_PRODUCT, SWIPE_UP_SHOP, PLAY_GAME_ON_FACEBOOK, VISIT_WORLD, OPEN_INSTANT_APP, JOIN_GROUP, GET_PROMOTIONS, SEND_UPDATES, INQUIRE_NOW, VISIT_PROFILE, CHAT_ON_WHATSAPP, EXPLORE_MORE, CONFIRM, JOIN_CHANNEL, MAKE_AN_APPOINTMENT, ASK_ABOUT_SERVICES, BOOK_A_CONSULTATION, GET_A_QUOTE, BUY_VIA_MESSAGE, ASK_FOR_MORE_INFO, VIEW_PRODUCT, VIEW_CHANNEL, WATCH_LIVE_VIDEO, JOIN_LIVE_VIDEO, IMAGINE, CALL, MISSED_CALL, CALL_NOW, CALL_ME, APPLY_NOW, BUY, GET_QUOTE, SUBSCRIBE, RECORD_NOW, VOTE_NOW, GIVE_FREE_RIDES, REGISTER_NOW, OPEN_MESSENGER_EXT, EVENT_RSVP, CIVIC_ACTION, SEND_INVITES, REFER_FRIENDS, REQUEST_TIME, SEE_MENU, SEARCH, TRY_IT, TRY_ON, LINK_CARD, DIAL_CODE, FIND_YOUR_GROUPS, START_ORDER&#125;*&lt;br&gt;The type of the action. Not all types can be used for all&lt;br&gt;ads. Check&lt;br&gt;[Ads Product Guide](https://www.facebook.com/business/ads-guide)&lt;br&gt;to see which type can be used for based on the `objective` of your&lt;br&gt;campaign.&lt;br&gt;&lt;br&gt;**[required]**&lt;br&gt;&lt;br&gt;&lt;br&gt;`value` *Object*&lt;br&gt;&lt;br&gt;**Default value: **`Vec`&lt;br&gt;JSON containing the call to action data.&lt;br&gt;&lt;br&gt;**[supports emoji]**&lt;br&gt;&lt;br&gt;&lt;br&gt;`android_url` *string*&lt;br&gt;&lt;br&gt;`ios_url` *string*&lt;br&gt;&lt;br&gt;`link` *URL*&lt;br&gt;&lt;br&gt;`app_link` *string*&lt;br&gt;&lt;br&gt;`page` *numeric string or integer*&lt;br&gt;&lt;br&gt;`link_format` *enum &#123;VIDEO_LEAD, VIDEO_LPP, VIDEO_NEKO, VIDEO_NON_LINK, VIDEO_SHOP, WHATSAPP_CATALOG_ATTACHMENT&#125;*&lt;br&gt;&lt;br&gt;`application` *numeric string or integer*&lt;br&gt;&lt;br&gt;`link_title` *string*&lt;br&gt;**[supports emoji]**&lt;br&gt;&lt;br&gt;&lt;br&gt;`link_description` *string*&lt;br&gt;**[supports emoji]**&lt;br&gt;&lt;br&gt;&lt;br&gt;`link_caption` *string*&lt;br&gt;&lt;br&gt;`product_link` *string*&lt;br&gt;&lt;br&gt;`get_movie_showtimes` *boolean*&lt;br&gt;&lt;br&gt;`sponsorship` *Object*&lt;br&gt;&lt;br&gt;`link` *URL*&lt;br&gt;&lt;br&gt;`image` *URL*&lt;br&gt;&lt;br&gt;`video_annotation` *Object*&lt;br&gt;&lt;br&gt;`annotations` *list&lt;Object&gt;*&lt;br&gt;&lt;br&gt;`start_time_in_sec` *int64*&lt;br&gt;&lt;br&gt;`end_time_in_sec` *int64*&lt;br&gt;&lt;br&gt;`link` *URL*&lt;br&gt;&lt;br&gt;`link_title` *string*&lt;br&gt;&lt;br&gt;`link_description` *string*&lt;br&gt;&lt;br&gt;`link_caption` *string*&lt;br&gt;&lt;br&gt;`image_url` *URL*&lt;br&gt;&lt;br&gt;`header_color` *string*&lt;br&gt;&lt;br&gt;`logo_url` *URL*&lt;br&gt;&lt;br&gt;`post_click_cta_title` *string*&lt;br&gt;&lt;br&gt;`post_click_description_title` *string*&lt;br&gt;&lt;br&gt;`offer_id` *numeric string or integer*&lt;br&gt;&lt;br&gt;`offer_view_id` *numeric string or integer*&lt;br&gt;&lt;br&gt;`advanced_data` *Object*&lt;br&gt;&lt;br&gt;`offer_id` *numeric string or integer*&lt;br&gt;&lt;br&gt;`lead_gen_form_id` *numeric string or integer*&lt;br&gt;&lt;br&gt;`referral_id` *numeric string or integer*&lt;br&gt;&lt;br&gt;`search_dialog_id` *numeric string or integer*&lt;br&gt;&lt;br&gt;`fundraiser_campaign_id` *numeric string or integer*&lt;br&gt;&lt;br&gt;`event_id` *numeric string or integer*&lt;br&gt;&lt;br&gt;`event_tour_id` *numeric string or integer*&lt;br&gt;&lt;br&gt;`app_destination` *enum &#123;MESSENGER, MESSENGER_EXTENSIONS, MESSENGER_GAMES, LINK_CARD, MARKETPLACE, WHATSAPP, INSTAGRAM_DIRECT, INSTAGRAM_LIVE_VIDEO, FACEBOOK_LIVE_VIDEO&#125;*&lt;br&gt;&lt;br&gt;`app_destination_page_id` *numeric string or integer*&lt;br&gt;&lt;br&gt;`is_canvas_video_transition_enabled` *boolean*&lt;br&gt;&lt;br&gt;`whatsapp_number` *string*&lt;br&gt;&lt;br&gt;`preinput_text` *string*&lt;br&gt;&lt;br&gt;`customized_message_page_cta_text` *string*&lt;br&gt;&lt;br&gt;`external_offer_provider_id` *numeric string or integer*&lt;br&gt;&lt;br&gt;`origins` *enum &#123;COMPOSER, CAMERA&#125;*&lt;br&gt;&lt;br&gt;`object_store_urls` *array&lt;string&gt;*&lt;br&gt;&lt;br&gt;`facebook_login_spec` *Object*&lt;br&gt;&lt;br&gt;`facebook_login_app_id` *numeric string or integer*&lt;br&gt;&lt;br&gt;`offer_type` *enum &#123;NO_OFFER, PERCENTAGE_BASED, AMOUNT_BASED&#125;*&lt;br&gt;&lt;br&gt;`offer_pct_call_to_action` *enum &#123;TEN&#125;*&lt;br&gt;&lt;br&gt;`offer_amt_call_to_action` *enum &#123;TEN&#125;*&lt;br&gt;&lt;br&gt;`product_id` *numeric string or integer*&lt;br&gt;&lt;br&gt;`group_id` *numeric string or integer*&lt;br&gt;&lt;br&gt;`channel_id` *string*&lt;br&gt;&lt;br&gt;`land_on_whatsapp_catalog` *enum&#123;1, 2&#125;*&lt;br&gt;&lt;br&gt;`land_on_whatsapp_profile` *string*&lt;br&gt;&lt;br&gt;`photo_replacement_preview_fbid` ** |
| `product_item_ids`&lt;br&gt;&lt;br&gt;*list&lt;string&gt;* | A list of Product Item IDs to use when rendering a dynamic ad preview.&lt;br&gt; |
| `start_date`&lt;br&gt;&lt;br&gt;*datetime* | Provide a start date for trip.* parameters in the creative&lt;br&gt; |
| `width`&lt;br&gt;&lt;br&gt;*int64* | Custom width of the resulting iframe, recommended at least 280 x 280 for the large right hand size widths.&lt;br&gt;Note: the parameter affects only the size of the iframe containing the preview object. It has no affect on the actual size of the previewed ad.&lt;br&gt; |

#### Fields

Reading from this edge will return a JSON formatted result:

```
&#123;
&quot;data&quot;: [],
&quot;paging&quot;: &#123;&#125;
&#125;
```

##### data

A list of [AdPreview](https://developers.facebook.com/docs/marketing-api/reference/ad-preview) nodes.

##### paging

For more details about pagination, see the [Graph API guide](https://developers.facebook.com/docs/graph-api/using-graph-api#paging).

#### Error Codes

| Error Code | Description |
| --- | --- |
| 100 | Invalid parameter |
| 80004 | There have been too many calls to this ad-account. Wait a bit and try again. For more info, please refer to /docs/graph-api/overview/rate-limiting#ads-management. |
| 190 | Invalid OAuth 2.0 Access Token |
| 104 | Incorrect signature |

## Creating

You can&#039;t perform this operation on this endpoint.

## Updating

You can&#039;t perform this operation on this endpoint.

## Deleting

You can&#039;t perform this operation on this endpoint.

