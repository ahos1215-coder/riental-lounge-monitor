# CRON 運用

## 失敗通知の方針（必須）
- cron-job.org の各ジョブで **execution of the cronjob fails** の通知を ON（1回失敗で通知）
- Render 側は **Failing deploy notifications** を ON
