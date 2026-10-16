> #### 小提醒
> 不太確定 PR 資訊要有哪些嗎？請先前往查看 [Code Review 文件](https://104cloud.sharepoint.com/:w:/s/QSM/EZc0Xl46jj5KlU6TjA2AaqkB65LDeNcLBfoqFZjhTTtbxQ?e=mpuafj)，也可以參考：[優秀 PR 範例](https://github.com/104corp/104qa-pytest-web/pull/234)

### 內容

- **Test Environment:** 
  - (ex: CAPP v3.20.0，[m104v2_3.20.0_05211537_production.apk](https://cac-travis-ci.s3-ap-northeast-1.amazonaws.com/android/M104/master/m104v2_3.20.0_05211537_production.apk) <平台/產品/版本...>)
- **Link:**
  - (ex: [[設定]修改手機，同步更新My104履歷表（API）](https://104tcm.testrail.net/index.php?/cases/view/1108634)<票務連結/Test Rail 連結...>)
- **Description:(請說明修改動機與範圍)**
  - (ex: 因為發現 xxx function 有會有不穩定的情況...故而 tests/xxx.py 新增邏輯... <問題敘述、功能敘述、流程敘述、斷言驗證等等...>)

---
### Check List
請 Coder/Reviewer 皆需確認以下的項目：
- [ ] 檢查自動化測試步驟與 Test Rail 一致
- [ ] 檢查符合 Coding Style
- [ ] 檢查 PR(Pull Request) 內容皆明確說明修改動機與範圍，並且能充分了解原因
- [ ] 自動化程式已跑過兩次以上 PASS 並附上兩次的測試結果
    - 若 "未" 開 Jira 票，請截圖 Report 並附在 PR 留言中即可
    - 若 "有" 開 Jira 票，請在票務留言中附上 Report.html 即可
- [ ] 自動化程式中的斷言都已新增清楚的 Message 進行說明
- [ ] 任何討論項目的結論皆有明確留言，以便日後追蹤

備註（任何額外資訊皆可補充）
  -  N/A