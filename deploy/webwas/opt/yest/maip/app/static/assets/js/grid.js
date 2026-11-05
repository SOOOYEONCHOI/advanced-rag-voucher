let GridUtil = {
    // WeZonGrid 버전 순서 변경 — 네이티브 moveRowsToUp/moveRowsToDown 사용
    // val : U,D / $grid : WeZonGrid 인스턴스
    changeOrder_wz: function (val, $grid) {
        if (!$grid || typeof $grid.moveRowsToUp !== 'function') {
            return;
        }
        if ($grid.getSelectedItems().length == 0) {
            Alert.alert('', '순서를 변경할 Row 를 선택하세요.');
            return;
        }

        let result = val == "U"
            ? $grid.moveRowsToUp()
            : $grid.moveRowsToDown();

        // result: null(서버모드) | {moved:true,...} | {moved:false, reason}
        if (!result || result.moved !== false) {
            return;
        }

        switch (result.reason) {
            case 'boundary':         // 페이징 없음 + 이미 첫/마지막 Row
            case 'paging-boundary':  // 페이징 경계
                Alert.alert('', val == "U" ? "첫번째 Row가 선택되었습니다." : "마지막 Row가 선택되었습니다.");
                break;
            case 'sort':
            case 'tree-sort':
                Alert.alert('', '정렬 상태에서는 순서를 변경할 수 없습니다.');
                break;
            case 'filter':
            case 'tree-filter':
                Alert.alert('', '필터 상태에서는 순서를 변경할 수 없습니다.');
                break;
            case 'group':
                Alert.alert('', '그룹 상태에서는 순서를 변경할 수 없습니다.');
                break;
            case 'tree-multi-parent':
                Alert.alert('', '같은 상위 항목의 Row 끼리만 순서를 변경할 수 있습니다.');
                break;
            default:
                break;
        }
    },
    adjustHeight: function (grid_config, rows_len) {
        //let grid_config = _this.grid_config;
        let height = grid_config.header.columnHeight + 3 + (grid_config.body.columnHeight + 3) * (rows_len + 2);
        //console.log('grid height', height);
        if (height < 150)
            height = 150;

        grid_config.target.css('height', height + 'px');
    },

    select_by_id: function (target_id_name, target_id, $grid) {
        if (!$grid || typeof $grid.getData !== 'function' || typeof $grid.setSelectionByIndex !== 'function') {
            return false;
        }

        let grid_data = $grid.getData();
        let index = grid_data.findIndex(item => item[target_id_name] == target_id);
        if (index < 0) {
            return false;
        }

        $grid.setSelectionByIndex(index);
        return true;
    },

    // 화면마다 WeZonGrid.create 를 직접 부르므로 만든 다음 줄에서 붙인다.
    // 컬럼 폭 합이 그리드보다 작으면 남는 폭을 컬럼 정의 폭(_widthRaw — 컬럼 설정을 저장했으면 그 폭) 비율대로 나눈다.
    // 크면 정의 폭 그대로 둔다(가로 스크롤). 그리드 폭이 바뀌거나 컬럼 레이아웃이 바뀌면(컬럼 설정) 다시 맞춘다.
    // setColumnWidth 는 표시 폭만 바꾸고 _widthRaw 는 두므로 늘 정의 폭에서 다시 계산한다.
    fitWidth: function (grid) {
        if (!grid || grid._fitWidthObserver) return;
        const fit = function () {
            const root = grid._containerEl.querySelector('.wzg-container');
            const body = root && root.querySelector('.wzg-body-scroll');
            if (!root || !body || !root.clientWidth) return;
            const cols = grid._columnManager.getVisibleColumns();
            const flex = cols.filter(function (c) { return !c._extra && typeof c._widthRaw === 'number'; });
            if (!flex.length) return;
            const fixed = cols.reduce(function (sum, c) { return flex.indexOf(c) < 0 ? sum + c.width : sum; }, 0);
            const room = root.clientWidth - (body.offsetWidth - body.clientWidth) - fixed;
            const base = flex.reduce(function (sum, c) { return sum + c._widthRaw; }, 0);
            const scale = Math.max(1, room / base);
            let used = 0;
            flex.forEach(function (c, index) {
                // 마지막 컬럼이 반올림 나머지를 받아 오른쪽 끝을 정확히 맞춘다.
                const width = scale > 1 && index === flex.length - 1 ? room - used : Math.floor(c._widthRaw * scale);
                used += width;
                if (c.width !== width) grid.setColumnWidth(c.dataField, width);
            });
        };
        // 컬럼 설정(setColumnLayout)과 resize(숨은 탭을 열 때 화면이 부른다)는 폭을 정의 폭으로 되돌린다. 그 뒤 다시 맞춘다.
        ['setColumnLayout', 'resize'].forEach(function (name) {
            const original = grid[name].bind(grid);
            grid[name] = function () {
                const result = original.apply(null, arguments);
                fit();
                return result;
            };
        });
        // 관찰 콜백 안에서 폭을 바꾸면 'ResizeObserver loop' 오류가 나므로 다음 프레임에 맞춘다.
        grid._fitWidthObserver = new ResizeObserver(function () { requestAnimationFrame(fit); });
        grid._fitWidthObserver.observe(grid._containerEl);
        const body = grid._containerEl.querySelector('.wzg-body-scroll');
        if (body) grid._fitWidthObserver.observe(body);   // 세로 스크롤 막대가 생기고 없어질 때
        fit();
    },
    // 화면 안 페이징 그리드에 다시 읽은 행을 넣는다. setData 는 선택을 지우고 페이지는 그대로 둔다(넘치면 마지막 페이지).
    // options.select: 그 id 의 행을 다시 고른다 — 다른 페이지로 옮겨 갔으면 그 페이지로 간다.
    // options.firstPage: 첫 페이지부터 보인다(조회 조건이 바뀌었을 때).
    // WeZonGrid 에 그리드 단위 공개 page 설정이 없어 pager 내부(_pager)를 여기 한 곳에서만 만진다.
    setRows: function (grid, rows, options) {
        options = options || {};
        grid.setData(rows);
        const index = options.select == null ? -1 : rows.findIndex(function (row) { return row.id === options.select; });
        // 화면 안 페이징(enablePaging)이 없는 그리드는 페이지를 옮기지 않는다
        if (grid._pager) {
            const size = grid._pager.getPageInfo().pageSize;
            if (index >= 0) grid._pager.setPage(Math.floor(index / size) + 1);
            else if (options.firstPage) grid._pager.setPage(1);
        }
        if (index >= 0) grid.setSelectionByRowId(options.select);
    },
    // 서버 페이징 그리드는 받은 페이지만 갖고 있고 WeZonGrid 는 서버 모드 내보내기를 막는다.
    // 조회 조건 전체(params + export=1 — 서버는 {rows, totalRows} 로 전부를 준다)를 받아
    // 같은 컬럼의 보이지 않는 그리드로 엑셀을 만든다.
    // SheetJS(0.9MB)는 엑셀을 누를 때 한 번만 싣는다. 화면마다 싣던 것을 뺐다.
    // 주소는 layout_page.html 의 window.XLSX_URL({% static %} — 운영은 해시 이름).
    _xlsxPromise: null,
    loadXlsx: function () {
        if (window.XLSX) { return Promise.resolve(); }
        if (!GridUtil._xlsxPromise) {
            GridUtil._xlsxPromise = new Promise(function (resolve, reject) {
                const script = document.createElement('script');
                script.src = window.XLSX_URL;
                script.onload = function () { resolve(); };
                script.onerror = function () {
                    GridUtil._xlsxPromise = null;
                    reject(new Error('엑셀 라이브러리를 불러오지 못했습니다.'));
                };
                document.head.appendChild(script);
            });
        }
        return GridUtil._xlsxPromise;
    },

    // 그리드를 엑셀로 내려받는다. 화면은 grid.exportToExcel 대신 이것을 부른다.
    exportExcel: function (grid, options) {
        return GridUtil.loadXlsx().then(function () { grid.exportToExcel(options); })
            .catch(function (error) { Alert.alert('', error.message); });
    },

    exportAll: function (grid, url, params, fileName) {
        AjaxUtil.getAsyncData(url, $.extend({}, params, { export: 1 }), function (res) {
            const box = $('<div>').css({ position: 'absolute', left: '-10000px', width: '800px' }).appendTo('body');
            const temp = WeZonGrid.create(box[0], { columnLayout: grid.getColumnLayout(), props: { height: 100 } });
            temp.setData(res.rows || []);
            GridUtil.exportExcel(temp, { fileName: fileName }).then(function () {
                temp.destroy();
                box.remove();
            });
        });
    },
};
