Graph API Version

[v25.0](#)

# Instagram (`instagram`)

Category of updates relating to activity on Instagram user

## `comments`

FBInstagramCommentsField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | value |
| `from`  IGCommentFromUser | Instagram-scoped ID and username of the Instagram user who created the comment |
| `id`  numeric string | id |
| `username`  string | username |
| `self_ig_scoped_id`  numeric string | self ig scoped id |
| `media`  IGCommentMedia | ID and product type of the IG Media the comment was created on |
| `id`  numeric string | ID of the IG Media the comment was created on |
| `media_product_type`  string | Product type of the IG Media the comment was created on |
| `ad_id`  numeric string | ID of the IG Ad the comment was created on |
| `ad_title`  string | Title of the IG Ad the comment was created on |
| `original_media_id`  numeric string | original\_media\_id |
| `id`  numeric string | The id of the object |
| `parent_id`  numeric string | ID of parent IG Comment if this comment was created on another IG Comment (i.g. a reply to another comment) |
| `text`  string | Comment text |

## `messaging_handover`

FBInstagramHOPField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | value |
| `sender`  IDName | sender |
| `id`  id | ID |
| `recipient`  IDName | recipient |
| `id`  id | ID |
| `timestamp`  unsigned integer | timestamp |
| `pass_thread_control`  object | pass\_thread\_control |
| `previous_owner_app_id`  numeric string | previous\_owner\_app\_id |
| `new_owner_app_id`  numeric string | new\_owner\_app\_id |
| `metadata`  string | metadata |
| `take_thread_control`  object | take\_thread\_control |
| `previous_owner_app_id`  numeric string | previous\_owner\_app\_id |
| `new_owner_app_id`  numeric string | new\_owner\_app\_id |
| `metadata`  string | metadata |
| `request_thread_control`  object | request\_thread\_control |
| `requested_owner_app_id`  numeric string | requested\_owner\_app\_id |
| `metadata`  string | metadata |
| `app_roles`  map | app\_roles |

## `live_comments`

FBInstagramLiveCommentsField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | value |
| `from`  IGCommentFromUser | Instagram-scoped ID and username of the Instagram user who created the comment |
| `id`  numeric string | id |
| `username`  string | username |
| `self_ig_scoped_id`  numeric string | self ig scoped id |
| `media`  IGCommentMedia | ID and product type of the IG Media the comment was created on |
| `id`  numeric string | ID of the IG Media the comment was created on |
| `media_product_type`  string | Product type of the IG Media the comment was created on |
| `ad_id`  numeric string | ID of the IG Ad the comment was created on |
| `ad_title`  string | Title of the IG Ad the comment was created on |
| `original_media_id`  numeric string | original\_media\_id |
| `id`  numeric string | The id of the object |
| `parent_id`  numeric string | ID of parent IG Comment if this comment was created on another IG Comment (i.g. a reply to another comment) |
| `text`  string | Comment text |

## `message_edit`

FBInstagramMessageEditField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `message_reactions`

FBInstagramMessageReactionsField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | value |
| `sender`  IDName | sender |
| `id`  id | ID |
| `recipient`  IDName | recipient |
| `id`  id | ID |
| `timestamp`  unsigned integer | timestamp |
| `reaction`  object | reaction |
| `mid`  string | mid |
| `action`  enum | action |
| `reaction`  enum | reaction |
| `emoji`  string | emoji |
| `folder`  string | folder |

## `messages`

FBInstagramMessagesField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | value |
| `sender`  IDName | sender |
| `id`  id | ID |
| `recipient`  IDName | recipient |
| `id`  id | ID |
| `timestamp`  unsigned integer | timestamp |
| `message`  object | message |
| `attachments`  list<FBInstagramMessageAttachmentData> | attachments |
| `type`  string | type |
| `payload`  object | payload |
| `ig_post_media_id`  numeric string | ig post media id |
| `url`  string | for url field in message attachment |
| `generic`  map | for generic template data field in message attachment |
| `reply_to`  object | reply\_to |
| `story`  object | story |
| `url`  string | url |
| `id`  string | id |
| `link_sticker_url`  string | link sticker url |
| `is_self_reply`  bool | is self reply |
| `is_self`  bool | is\_self |
| `is_deleted`  bool | is\_deleted |
| `folder`  string | folder |

## `mentions`

Notifies you when an Instagram User @mentions you in a comment or caption on a media object.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | Contents of the update |
| `media_id`  string | ID of media containing comment with mention. |
| `comment_id`  string | ID of comment with mention. |

## `messaging_referral`

InstagramMessagingReferralField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | the referral information along with sender and business ids, and timestamp |
| `sender`  MessengerParticipantID | sender |
| `id`  numeric string | id |
| `recipient`  MessengerParticipantID | recipient |
| `id`  numeric string | id |
| `timestamp`  unsigned integer | timestamp |
| `referral`  object | referral |

## `messaging_seen`

InstagramMessagingSeenField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | Contents of the seen state update |
| `sender`  IDName | sender |
| `id`  id | ID |
| `recipient`  IDName | recipient |
| `id`  id | ID |
| `timestamp`  unsigned integer | timestamp |
| `read`  object | read |

## `messaging_postbacks`

InstagramPostbackField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | value |
| `sender`  IDName | sender of the postback |
| `id`  id | ID |
| `recipient`  IDName | recipient |
| `id`  id | ID |
| `is_self`  bool | is self |
| `timestamp`  unsigned integer | timestamp when it was sent |
| `postback`  object | postback payload |
| `title`  string | title of postback |
| `payload`  string | payload of postback |
| `referral`  object | referral details |
| `mid`  string | mid |

## `standby`

InstagramStandbyField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  string | value |

## `story_insights`

Notifies you when a story expires. Metrics with counts of less than 5 will be returned as `-1`.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | The result values |
| `media_id`  numeric string | Media Id of the Story |
| `impressions`  integer | Impressions |
| `reach`  integer | Reach |
| `taps_forward`  integer | Taps forward |
| `taps_back`  integer | Taps back |
| `exits`  integer | Exits |
| `replies`  integer | Replies |
