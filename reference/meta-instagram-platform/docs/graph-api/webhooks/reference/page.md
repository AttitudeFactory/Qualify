Graph API Version

[v25.0](#)

# Page (`page`)

Page profile webhook fields you can subscribe to. In order for these webhooks to be sent to an app's webhook callback URL, a page admin with MODERATE privileges must grant the app the pages\_manage\_metadata permission.

## `messaging_account_linking`

MessengerAccountLinkField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `business_integrity`

MessengerBusinessIntegrityField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | value |
| `timestamp`  unsigned integer | timestamp |
| `status`  string | status |
| `violations`  list<MessengerBusinessIntegrityViolationData> | violations |
| `type`  string | type |
| `description`  string | description |
| `url`  string | url |
| `restrictions`  list<MessengerBusinessIntegrityFeatureLimitData> | restrictions |
| `feature`  string | feature |
| `status`  string | status |
| `description`  string | description |
| `applied_time`  unsigned integer | applied\_time |
| `expiration_time`  unsigned integer | expiration\_time |
| `action_events`  list<MessengerBusinessIntegrityActionEventData> | action\_events |
| `type`  string | type |
| `status`  string | status |
| `created_time`  unsigned integer | created\_time |
| `updated_time`  unsigned integer | updated\_time |

## `call_permission_reply`

MessengerCallPermissionReplyField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | value |
| `sender`  MessengerCommerceSenderData | sender |
| `recipient`  IDName | recipient |
| `id`  id | ID |
| `name`  string | Name |
| `timestamp`  integer | timestamp |
| `call_permission_reply`  MessengerCommerceCallPermissionReplyData | call\_permission\_reply |
| `response`  string | response |
| `expiration_timestamp`  integer | expiration\_timestamp |

## `call_settings_update`

MessengerCallSettingsUpdateField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | value |
| `timestamp`  unsigned integer | timestamp |
| `audio_enabled`  bool | audio\_enabled |
| `icon_enabled`  bool | icon\_enabled |
| `video_enabled`  bool | video enabled |
| `call_routing`  CallRouting | call\_routing |
| `ring_target`  string | ring\_target |
| `call_hours`  CallHours | call\_hours |

## `calls`

MessengerCallsField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `messaging_customer_information`

MessengerCustomerInformationField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | value |
| `sender`  IDName | sender |
| `id`  id | ID |
| `name`  string | Name |
| `recipient`  IDName | recipient |
| `id`  id | ID |
| `name`  string | Name |
| `timestamp`  unsigned integer | timestamp |
| `messaging_customer_information`  MessengerCommerceCustomerInfomationScreensData | messaging\_customer\_information |
| `screens`  list<MessengerCommerceCustomerInfomationScreenData> | screens |
| `screen_id`  string | the ID of the screen |
| `responses`  list<KeyValue:string,string> | the information entered by the user in the customer information screen |
| `key`  string | Key of the pair |
| `value`  string | Value of the pair |

## `group_feed`

Describes comments made to Page's post in a Facebook Group.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | value |
| `recipient`  IDName | recipient |
| `id`  id | ID |
| `name`  string | Name |
| `from`  IDName | from |
| `id`  id | ID |
| `name`  string | Name |
| `group_id`  numeric string | group\_id |
| `comment_id`  numeric string | comment\_id |
| `post_id`  numeric string | post\_id |
| `created_time`  int32 | created\_time |
| `item`  string | item |
| `verb`  string | verb |
| `message`  string | message |
| `field`  string | field |
| `parent_id`  numeric string | parent\_id |

## `messaging_handovers`

MessengerHandoverField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `messaging_in_thread_lead_form_submit`

MessengerLeadGenInThreadFormSubmitAckField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `message_context`

MessengerMessageContextField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | value |
| `sender`  MessengerParticipantID | sender |
| `id`  numeric string | id |
| `recipient`  MessengerParticipantID | recipient |
| `id`  numeric string | id |
| `timestamp`  unsigned integer | timestamp |
| `message_context`  object | message\_context |
| `detections`  list<MessengerMessageContextDetections> | detections |
| `type`  string | type |
| `id`  string | id |
| `mid`  string | mid |
| `event_name`  string | event\_name |
| `model`  string | model |
| `capi_standard_event`  string | capi\_standard\_event |
| `model_name`  string | model\_name |
| `model_score`  float | model\_score |
| `model_version`  int32 | model\_version |
| `eligible_for_ads_reporting`  bool | eligible for ads reporting |
| `custom_data`  MessengerMessageContextCustomData | custom\_data |
| `currency`  string | currency |
| `value`  float | value |
| `suggestions`  list<MessengerMessageContextSuggestions> | suggestions |
| `type`  string | type |
| `id`  string | id |
| `mid`  string | mid |
| `event_name`  string | event\_name |
| `model`  string | model |

## `message_deliveries`

MessengerMessageDeliveryReceiptField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `message_echoes`

MessengerMessageEchoField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `message_edits`

MessengerMessageEditField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | value |
| `sender`  MessengerCommerceSenderData | sender |
| `recipient`  IDName | recipient |
| `id`  id | ID |
| `name`  string | Name |
| `timestamp`  unsigned integer | timestamp |
| `message_edit`  object | message\_edit |
| `mid`  string | mid |
| `text`  string | text |
| `num_edit`  int32 | num\_edit |

## `message_reads`

MessengerMessageReadReceiptField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `message_template_status_update`

MessengerMessageTemplateStatusUpdateField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `messages`

MessengerMessagesField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `messaging_integrity`

MessengerMessagingIntegrityField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `messaging_optins`

MessengerNotificationMessagesOptinField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `messaging_optins`

MessengerOneTimeOptinField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `messaging_policy_enforcement`

MessengerPolicyField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | value |
| `recipient`  IDName | recipient |
| `id`  id | ID |
| `name`  string | Name |
| `timestamp`  unsigned integer | timestamp |
| `policy_enforcement`  MessengerCommercePolicyData | policy\_enforcement |
| `action`  string | action |
| `reason`  string | reason |

## `messaging_postbacks`

MessengerPostbackField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `message_reactions`

MessengerReactionsField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | value |
| `sender`  MessengerParticipantID | sender |
| `id`  numeric string | id |
| `recipient`  MessengerParticipantID | recipient |
| `id`  numeric string | id |
| `timestamp`  unsigned integer | timestamp |
| `reaction`  object | reaction |
| `mid`  string | mid |
| `action`  enum | action |
| `emoji`  string | emoji |
| `reaction`  enum | reaction |

## `messaging_referrals`

MessengerReferralField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `response_feedback`

MessengerResponseFeedbackField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `send_cart`

MessengerSendCartField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `affiliation`

Describes changes to a page's Affliation profile field.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `attire`

Describes changes to a page's Attire profile field.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `awards`

Describes changes to a page's Awards profile field.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `birthday`

Describes changes to a page's Birthday profile field.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `category`

Describes changes to a page's Category field. There can be up to three categories describing a page's topic, business, or person.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  enum | The result value. |

## `page_change_proposal`

Data for page change proposal.

| Field | Description |
| --- | --- |
| `action`  enum | The action of the proposal, can be created, accepted\_manually, rejected\_manually and accepted\_automatically |
| `field`  string | Name of the updated field |
| `value`  [PageChangeProposal](/docs/graph-api/reference/page-change-proposal/) | The contents of the proposal |
| `id`  numeric string | The ID of the proposal |
| `upcoming_change_info`  [PageUpcomingChange](/docs/graph-api/reference/page-upcoming-change/) | The upcoming change info of this proposal if the proposal will be automatically accepted |
| `id`  numeric string | The ID of the upcoming change |
| `effective_time`  datetime | The time when the upcoming change will become effective |
| `timer_status`  enum | The status of the timer associated with this change |
| `category`  string | The category of the proposed change |
| `acceptance_status`  enum | Indicate whether it was accepted or rejected only meaningful when the proposal is not pending |

## `company_overview`

Describes changes to a page's Company Overview profile field.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  string | The result value. |

## `culinary_team`

Describes changes to a page's Culinary Team profile field.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `current_location`

Describes changes to a page's Current Location profile field.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `description`

Describes changes to a page's Story Description profile field.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `email`

Describes changes to a page's Email profile field.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `feed`

Describes nearly all changes to a Page's feed, such as Posts, shares, likes, etc. The values received depend on the types of changes made to the Page's feed. Webhooks are not sent for Ad Posts, but are sent for Comments on Ad Posts. Notifications for Page likes will only be sent for Pages that have fewer than 10K likes.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | The contents of the update |
| `edited_time`  datetime | edited\_time |
| `from`  object | The sender information |
| `id`  numeric string | The ID of the sender |
| `name`  string | The name of the sender |
| `post`  [PagePost](/docs/graph-api/reference/page-post/) | Provide additional content about a post such as 'type' (e.g. photo, video), 'status\_type' (e.g. added\_photos), 'is\_published' (e.g. true/false), 'updated\_time', 'permalink\_url', 'promotion\_status' (e.g. inactive, extendable) |
| `status_type`  string | Description of the type of a status update. |
| `is_published`  bool | Indicates whether a scheduled post was published (applies to scheduled Page Post only, for users post and instanlty published posts this value is always true) |
| `updated_time`  datetime | The time the post was last updated, which occurs when a user comments on the post. |
| `permalink_url`  uri | The permanent static URL to the post on www.facebook.com. Example: https://www.facebook.com/FacebookforDevelopers/posts/10153449196353553 |
| `is_hidden`  bool | Whether the post is hidden or not |
| `link`  string | The link to attached content |
| `message`  string | The message that is part of the content |
| `photo`  string | The link to an attached photo |
| `photo_ids`  list<id> | The IDs of the photos that were added to an album |
| `photos`  list<string> | The links to any attached photos |
| `post_id`  token with structure: Post ID | The post ID |
| `story`  string | The story—only logged for a milestone item |
| `title`  string | The title—only logged for a milestone item |
| `video`  string | The link to an attached video |
| `video_flag_reason`  int32 | The code why the video is flagged. Available when a video is blocked, muted, or unblocked. (Reason Code 1: Your video may contain content that belongs to someone else) |
| `action`  string | The type of action taken |
| `album_id`  id | The album ID |
| `comment_id`  string | The comment ID |
| `created_time`  datetime | The timestamp of when the object was created |
| `event_id`  string | The ID of the event, if the feed post is an event creation story |
| `item`  enum {album, address, comment, connection, coupon, event, experience, group, group\_message, interest, link, mention, milestone, note, page, picture, platform-story, photo, photo-album, post, profile, question, rating, reaction, relationship-status, share, status, story, timeline cover, tag, video} | The type of item |
| `open_graph_story_id`  id | The ID of the open graph object |
| `parent_id`  token with structure: Post ID | The parent ID |
| `photo_id`  id | The photo ID |
| `reaction_type`  string | The type of the user reaction |
| `published`  int32 | Whether the post is published |
| `recipient_id`  id | The recipient ID |
| `share_id`  id | The share ID |
| `verb`  enum {add, block, edit, edited, delete, follow, hide, mute, remove, unblock, unhide, update} | The type of action taken |
| `video_id`  id | The video ID |

## `founded`

Describes changes to a page's Founded profile field. This is different from the Start Date field.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  string | The result value. |

## `general_info`

Describes changes to a page's General Information profile field.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  string | The result value. |

## `general_manager`

Describes changes to a page's General Manager profile field.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `hometown`

Describes changes to a page's Homewtown profile field.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `hours`

Describes changes to a page's Hours profile field.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `inbox_labels`

PageInboxLabelsField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | value |
| `user`  IDName | user |
| `id`  id | ID |
| `action`  enum | action |
| `label`  object | label |

## `invoice_access_invoice_draft_change`

PageInvoiceAccessInvoiceDraftChangeField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | value |
| `page_id`  integer | page\_id |
| `invoice_id`  integer | invoice\_id |
| `external_invoice_id`  string | external\_invoice\_id |
| `updates`  object | updates |
| `shipping_address`  object | shipping\_address |
| `previous_value`  McomInvoiceShippingAddress | previous\_value |
| `contact_info`  McomInvoiceContactInfo | contact\_info |
| `name`  string | name |
| `phone_number`  string | phone\_number |
| `address_details`  McomInvoiceAddressDetails | address\_details |
| `country`  string | country |
| `address_line_1`  string | address\_line\_1 |
| `address_line_2`  string | address\_line\_2 |
| `administrative_area`  string | administrative\_area |
| `subadministrative_area`  string | subadministrative\_area |
| `locality`  string | locality |
| `sublocality`  string | sublocality |
| `postal_code`  string | postal\_code |
| `new_value`  McomInvoiceShippingAddress | new\_value |
| `contact_info`  McomInvoiceContactInfo | contact\_info |
| `name`  string | name |
| `phone_number`  string | phone\_number |
| `address_details`  McomInvoiceAddressDetails | address\_details |
| `country`  string | country |
| `address_line_1`  string | address\_line\_1 |
| `address_line_2`  string | address\_line\_2 |
| `administrative_area`  string | administrative\_area |
| `subadministrative_area`  string | subadministrative\_area |
| `locality`  string | locality |
| `sublocality`  string | sublocality |
| `postal_code`  string | postal\_code |
| `payments`  object | payments |
| `previous_value`  list<P2MInvoicePayment> | previous\_value |
| `payment_amount`  McomInvoiceCurrencyInfo | payment\_amount |
| `currency`  string | currency |
| `amount`  string | amount |
| `payment_method`  string | payment\_method |
| `buyer_id`  string | buyer\_id |
| `order_id`  string | order\_id |
| `payment_id`  string | payment\_id |
| `creation_time`  integer | creation\_time |
| `metadata`  P2MInvoicePaymentMetadata | metadata |
| `bank_slip`  P2MInvoiceBankSlipMetadata | bank\_slip |
| `image_url`  string | image\_url |
| `media_id`  numeric string | media\_id |
| `bank_transfer_id`  string | bank\_transfer\_id |
| `transaction_time`  integer | transaction\_time |
| `validation_status`  string | validation\_status |
| `validation_error`  string | validation\_error |
| `receiver_name`  string | receiver\_name |
| `receiver_bank_account_id`  string | receiver\_bank\_account\_id |
| `receiver_bank_code`  string | receiver\_bank\_code |
| `sender_name`  string | sender\_name |
| `sender_bank_account_id`  string | sender\_bank\_account\_id |
| `sender_bank_code`  string | sender\_bank\_code |
| `new_value`  list<P2MInvoicePayment> | new\_value |
| `payment_amount`  McomInvoiceCurrencyInfo | payment\_amount |
| `currency`  string | currency |
| `amount`  string | amount |
| `payment_method`  string | payment\_method |
| `buyer_id`  string | buyer\_id |
| `order_id`  string | order\_id |
| `payment_id`  string | payment\_id |
| `creation_time`  integer | creation\_time |
| `metadata`  P2MInvoicePaymentMetadata | metadata |
| `bank_slip`  P2MInvoiceBankSlipMetadata | bank\_slip |
| `image_url`  string | image\_url |
| `media_id`  numeric string | media\_id |
| `bank_transfer_id`  string | bank\_transfer\_id |
| `transaction_time`  integer | transaction\_time |
| `validation_status`  string | validation\_status |
| `validation_error`  string | validation\_error |
| `receiver_name`  string | receiver\_name |
| `receiver_bank_account_id`  string | receiver\_bank\_account\_id |
| `receiver_bank_code`  string | receiver\_bank\_code |
| `sender_name`  string | sender\_name |
| `sender_bank_account_id`  string | sender\_bank\_account\_id |
| `sender_bank_code`  string | sender\_bank\_code |

## `leadgen`

Describes changes to a page's leadgen settings.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | Result values. |
| `adgroup_id`  id | The ID of the ad group that the lead is part of |
| `ad_id`  id | The ID of the ad that the lead is part of |
| `created_time`  datetime | When the lead was created |
| `leadgen_id`  id | The ID of the created lead |
| `page_id`  id | The ID of the page that the lead belongs to |
| `form_id`  id | The ID of the form that the lead is part of |

## `live_videos`

Describes changes to a page's live video status.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | Content of the update |
| `id`  id | The ID of the live video |
| `status`  enum | The status of the live video |

## `location`

Describes changes to a page's Location profile field, including the street address, city/state, or zip code fields.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `members`

Describes changes to a page's Members profile field.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `mention`

Describes new mentions of a page, including mentions in comments, posts, etc. Some `comment_id` and `post_id` fields returned in mention webhooks may not be queried due to missing permissions including privacy issues.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | The contents of the update |
| `from`  object | The sender information. Only availabe for Workplace community |
| `id`  numeric string | The ID of the sender |
| `name`  string | The name of the sender |
| `link`  string | The attachement link in the content that mentioned the page |
| `message`  string | The message that is part of the content that mentioned the page |
| `message_tags`  [list<EntityAtTextRange>](/docs/graph-api/reference/entity-at-text-range/) | Profiles tagged in the message. Workplace only apps |
| `id`  numeric string | ID of the profile |
| `length`  unsigned int32 | Number of characters in the text indicating the object |
| `name`  string | Name of the object |
| `offset`  unsigned int32 | The character offset in the source text of the text indicating the object |
| `type`  enum {user, page, event, group, application} | Type of the object |
| `photo`  string | The link to an attached photo in the content that mentioned the page |
| `photos`  list<string> | The links to attached photos in the content that mentioned the page |
| `post_id`  token with structure: Post ID | The ID of the post that mentioned the page |
| `video`  string | The link to an attached video in the content that mentioned the page |
| `action`  string | The type of action taken |
| `album_id`  id | The album ID |
| `comment_id`  string | The comment ID |
| `created_time`  datetime | The timestamp of when the object was created |
| `event_id`  string | The ID of the event, if the feed post is an event creation story |
| `item`  enum {album, address, comment, connection, coupon, event, experience, group, group\_message, interest, link, mention, milestone, note, page, picture, platform-story, photo, photo-album, post, profile, question, rating, reaction, relationship-status, share, status, story, timeline cover, tag, video} | The type of item |
| `open_graph_story_id`  id | The ID of the open graph object |
| `parent_id`  token with structure: Post ID | The parent ID |
| `photo_id`  id | The photo ID |
| `reaction_type`  string | The type of the user reaction |
| `published`  int32 | Whether the post is published |
| `recipient_id`  id | The recipient ID |
| `share_id`  id | The share ID |
| `verb`  enum {add, block, edit, edited, delete, follow, hide, mute, remove, unblock, unhide, update} | The type of action taken |
| `video_id`  id | The video ID |

## `mission`

Describes changes to a page's Mission profile field.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  string | The result value. |

## `name`

Describes changes to a page's Name profile field.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  string | The page's name |

## `parking`

Describes changes to a page's Parking profile field.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `payment_options`

Describes change to a page's Payment profile field.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `personal_info`

Describes changes to a page's Personal Information profile field.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `personal_interests`

Describes changes to a page's Personal Interests profile field.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `phone`

Describes changes to a page's Phone profile field.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `picture`

Describes changes to a page's profile picture.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `price_range`

Describes changes to a page's Price Range profile field.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `product_review`

Describes changes to a page's product review settings.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | The result values. |
| `product_item_id`  id | The Product Item ID that this review is about |
| `status`  enum {NO\_REVIEW, PENDING, REJECTED, APPROVED, OUTDATED} | The review status |
| `reasons`  list<string> | A list of reasons why the product item was rejected. Only set if the status is REJECTED. |

## `products`

Describes changes to a page's Products profile field.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  string | The result value. |

## `public_transit`

Describes changes to a page's Public Transit profile field.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `ratings`

Describes changes to a page's ratings, including new ratings or a user's comments or reactions on a rating.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | The result values. |
| `comment_id`  string | The Comment ID if a comment was made on a rating |
| `created_time`  datetime | Timestamp for when the action took place |
| `item`  enum | The type of object that was updated |
| `message`  string | The Comment message if a comment was made on a rating |
| `open_graph_story_id`  id | Open Graph story ID of this rating for added or edited ratings |
| `parent_id`  token with structure: Post ID | The parent object ID, which can be the rating object or another comment |
| `photo`  string | The Photo URI if a photo was attached to a comment on a rating |
| `post_id`  token with structure: Post ID | The Post ID of the rating |
| `rating`  int32 | The star rating on created or edited ratings |
| `review_text`  (string) or (null) | The Review text on created or edited ratings |
| `reaction_type`  string | The user's reaction type, if the user selects a reaction for a rating |
| `recommendation_type`  enum | Whether or not this recommendation was "positive" or "negative" |
| `reviewer_id`  id | The ID of the reviewer on created or edited ratings |
| `reviewer_name`  string | The name of reviewer on created or edited ratings |
| `sender_id`  id | The ID of the user or page taking an action on a rating |
| `sender_name`  string | The name of the user or page taking an action on a rating |
| `verb`  enum {add, block, edit, edited, delete, follow, hide, mute, remove, unblock, unhide, update} | The type of action taken on a rating |

## `page_upcoming_change`

Webhooks data for page upcoming changes.

| Field | Description |
| --- | --- |
| `action`  enum | The action happened for this upcoming change |
| `field`  string | Name of the updated field |
| `value`  [PageUpcomingChange](/docs/graph-api/reference/page-upcoming-change/) | The contents of the upcoming change |
| `page`  [Page](/docs/graph-api/reference/page/) | The associated page of this upcoming change |
| `name`  string | The name of the Page |
| `effective_time`  datetime | The time when the upcoming change will become effective |
| `change_type`  enum | The type of the upcoming change |
| `timer_status`  enum | The status of the timer associated with this change |
| `proposal`  [PageChangeProposal](/docs/graph-api/reference/page-change-proposal/) | The proposal associated with the change, only valid when change\_type is knowledge\_proposal |
| `category`  string | The category of the proposed change |
| `acceptance_status`  enum | Indicate whether it was accepted or rejected only meaningful when the proposal is not pending |

## `videos`

Describes changes to the encoding status of a video on a page.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | Content of the update |
| `id`  id | ID of the video |
| `status`  object | Status of the video |
| `video_status`  enum | Status of the video |

## `website`

Describes changes to a page's Website profile field.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
