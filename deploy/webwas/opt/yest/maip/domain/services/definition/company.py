from configurations import settings
from domain.services.sql import DbUtil
from domain.services.logging import LogWriter

class CompanyService():
    def __init__(self):
        return


    def get_material_list(self):
        sql= '''
            select id as id
                , "Code" as code
                , "Name" as name
            from material m
        '''

        try:
            items = DbUtil.get_rows(sql, None)
        except Exception as ex:
            LogWriter.add_dblog('error', 'CompanyService.get_material_list', ex)
            raise ex

        return items


    def get_mat_comp_uprice_list(self, company_id):
        dic_param = {'company_id':company_id}

        sql = '''
            select "Material_id" as material_id
            from mat_comp_uprice mcu 
            where "Company_id" = %(company_id)s
        '''

        items = DbUtil.get_rows(sql, dic_param)

        cond = []
        if len(items) > 0:
            for i in range(0, len(items)):
                cond[i] = repr(items[i].get("material_id"))

        dic_param['cond'] = cond

        #if len(items) > 0:
        #	for i in range(0, len(items)):
        #		cond += repr(items[i].get("material_id")) + ", "
        #cond += "//"

        #cond = cond.replace(", //", "")

        sql = '''
            select m.id as material_id
                , mcu.id as mcu_id
                , m."Code" as material_code
                , m."Name" as material_name
                , mcu."FormerUnitPrice" as former_unit_price
                , m."UnitPrice" as unit_price
                , mcu."ApplyStartDate" as apply_start_date
                , mcu."ApplyEndDate" as apply_end_date
                , mcu."ChangerName" as changer_name
                , mcu."ChangeDate" as change_date
            from mat_comp_uprice mcu 
            inner join material m on m.id = mcu."Material_id" 
            where mcu."Company_id" = %(company_id)s
            union all
            select m2.id as material_id 
                , null as mcu_id
                , m2."Code" as material_code
                , m2."Name" as material_name
                , 0 as former_unit_price
                , 0 as unit_price
                , null as apply_start_date
                , null as apply_end_date
                , '' as changer_name
                , null as change_date
            from material m2 
        '''

        if cond:
            sql += '''
            where m2.id not in (%(cond)s)
            '''
          
        try:
            items = DbUtil.get_rows(sql, dic_param)
        except Exception as ex:
            LogWriter.add_dblog('error', 'CompanyService.get_mat_com_uprice_list', ex)
            raise ex
        return items


    def get_company_list(self, comp_type, group_name, keyword):
        """
        """
        try:
            sql = '''
                select c.id as id
                    , c."Name" as name
                    , c."EngName" as eng_name
                    , c."Code" as comp_code
                    , c."Code2" as comp_code2
                    , fn_class_data_text('company', 'company_type', c.id) as company_type_name
                    , c."BusinessNumber" as business_number
                    , c."CEOName" as ceo_name
                    , c."ZipCode" as zip_code
                    , c."Address" as address
                    , c."TelNumber" as tel_number
                    , c."FaxNumber" as fax_number
                    , c."BusinessType" as business_type
                    , c."BusinessItem" as business_item
                    , c."Email" as email
                    , c."PurchaseSalesDeadline" as purchase_sales_deadline
                    , c."LastTradingDay" as last_trading_day
                    , c."OurManager" as our_manager
                    , c."SalesManager" as sales_manager
                    , c."SalesManagerPhone" as sales_manager_phone
                    , c."AccountManager" as account_manager
                    , c."AccountManagerPhone" as account_manager_phone
                    , c."TrandingBank" as tranding_bank
                    , c."AccountHolder" as account_holder
                    , c."AccountNumber" as account_number
                    , c."CreditLimitAmount" as credit_limit_amount
                    , c."PaymentCondition" as payment_condition
                    , c."Description" as description
                    , c."GroupName" as group_name
                    , c."PaymentMethod" as pay_method
                    , c."CompanyTelNumber" as company_tel_number
                    , (select string_agg(fn_code_name('company_type', "Tag"), ', ') from class_data where "DataPk" = c.id) as company_type_names
                from company c 
                where 1 = 1
            '''

            if comp_type:
                sql += ''' and exists (select 1 
                        from class_data cd 
                        where cd."TableName" = 'company'
                        and cd."ClassName" = 'company_type'
                        and cd."DataPk" = c.id
                        and cd."Tag" = %(comp_type)s
                    )
                '''
            else:
                sql += ''' and exists (select 1 
                        from class_data cd 
                        where cd."TableName" = 'company'
                        and cd."ClassName" = 'company_type'
                        and cd."DataPk" = c.id
                        and cd."Tag" <> 'parts-maker'
                    )
                '''

            if keyword:
                sql += ''' and upper(c."Name") like '%%' || upper(%(keyword)s) || '%%'
                '''
            if group_name:
                sql += ''' and upper(c."GroupName") like '%%' || upper(%(group_name)s) || '%%'
                '''
            sql += ''' order by c."CompanyType", c."Name"
            '''

            dc = {}
            dc['comp_type']= comp_type
            dc['group_name']= group_name
            dc['keyword']= keyword
            items = DbUtil.get_rows(sql, dc)

        except Exception as ex:
            LogWriter.add_dblog('error', 'CompanyService.get_company_list', ex)
            raise ex

        return items


    def get_company_detail(self, id):
        sql = '''
            select c.id as id
                , c."Name" as name
                , c."EngName" as eng_name
                , c."Code" as comp_code
                , c."Code2" as comp_code2
                , c."BusinessNumber" as business_number
                , c."CEOName" as ceo_name
                , c."ZipCode" as zip_code
                , c."Address" as address
                , c."TelNumber" as tel_number
                , c."FaxNumber" as fax_number
                , c."BusinessType" as business_type
                , c."BusinessItem" as business_item
                , c."Email" as email
                , c."PurchaseSalesDeadline" as purchase_sales_deadline
                , c."LastTradingDay" as last_trading_day
                , c."OurManager" as our_manager
                , c."SalesManager" as sales_manager
                , c."SalesManagerPhone" as sales_manager_phone
                , c."AccountManager" as account_manager
                , c."AccountManagerPhone" as account_manager_phone
                , c."TrandingBank" as tranding_bank
                , c."AccountHolder" as account_holder
                , c."AccountNumber" as account_number
                , c."CreditLimitAmount" as credit_limit_amount
                , c."PaymentCondition" as payment_condition
                , c."Description" as description
                , c."Homepage" as homepage
                , c."FirstTradingDay" as first_trading_day
                , c."ReceivableAmount" as receivable_amount
                , c."UnpaidAmount" as unpaid_amount
                , c."ManageRemark" as manage_remark
                , c."GroupName" as group_name
                , c."MainProduct_id" as main_prod
                , c."PaymentMethod" as pay_method
                , c."CompanyTelNumber" as company_tel_number
            from company c 
            where c.id = %(id)s
        '''
        data = {}
        try:
            data = DbUtil.get_row(sql, {'id': id})

        except Exception as ex:
            LogWriter.add_dblog('error', 'CompanyService.get_company_detail', ex)
            raise ex

        return data


    def get_company_type(self, comp_id):
        sql = '''
            select cd."Tag" as company_type
            from class_data cd
            where cd."TableName" = 'company'
            and cd."ClassName" = 'company_type'
            and cd."DataPk" = %(comp_id)s
        '''
        data = {}
        try:
            data = DbUtil.get_rows(sql, {'comp_id': comp_id})

        except Exception as ex:
            LogWriter.add_dblog('error', 'CompanyService.get_company_type', ex)
            raise ex

        return data


    def get_company_detail2(self, id):
        sql = '''
            select mcu.id as mcu_id
                , m.id as material_id
                , m."Code" as material_code
                , m."Name" as material_name
                , mcu."FormerUnitPrice" as former_unit_price
                , mcu."UnitPrice" as unit_price
                , mcu."ApplyStartDate" as apply_start_date
                , mcu."ApplyEndDate" as apply_end_date
            from mat_comp_uprice mcu 
            inner join material m on mcu."Material_id" = m.id 
            where mcu.id = %(id)s
        '''
        data = {}
        try:
            items = DbUtil.get_rows(sql, {'id': id})
            if len(items) > 0:
                data = items[0]
        except Exception as ex:
            LogWriter.add_dblog('error', 'CompanyService.get_company_detail', ex)
            raise ex

        return data


    def get_customer_list(self, keyword):
        sql='''
        with A as (
			select c.id as "Customer_id" 
			, c."Name"
			, c."Address"  
			, c."TelNumber"
			, c."AccountManager" 
			, c."FaxNumber"
			, c."BusinessNumber"
            , c."Description"
			from company c 
			where 1=1
            '''
        if keyword:
            sql += ''' and c."Name" like '%%' || %(keyword)s || '%%'
            '''
        sql += ''' ), B as (
			select dp."Customer_id", count(*) as dp_cnt
			from A 
			inner join delivery_place dp on dp."Customer_id" = A."Customer_id"
			group by dp."Customer_id"
		)
		select A.*, coalesce(B.dp_cnt,0) as dp_cnt
		from A 
		left join B on B."Customer_id" = A."Customer_id"
        where 1 = 1 
        order by A."Name"
        '''

        try: 
            dc = {}
            dc['keyword'] = keyword
            items = DbUtil.get_rows(sql, dc)
        except Exception as ex:
            LogWriter.add_dblog('error', 'DeliveryPlace ',ex)
        return items

    def get_delivery_list(self, customer_id):
        items=[]
        sql = '''
        select
            dp.id
            , dp."Code"
            , dp."Name" as "Name"
            , dp."Address" as "Address"
            , dp."BusinessNumber" as "BusinessNumber"
            , dp."TelNumber" as "TelNumber"
            , dp."FaxNumber" as "FaxNumber"
            , dp."Homepage" as "Homepage"
            , dp."Description" as "Description"
            , dp."Charger"
            , dp."PhoneNumber"
        from delivery_place dp
        where 1=1
        and dp."Customer_id" = %(customer_id)s
        '''
        try:
            dc={}
            dc['customer_id'] = customer_id
            items = DbUtil.get_rows(sql,dc)
        except Exception as ex:
            LogWriter.add_dblog('error','DefinitionService.get_delivery_list', ex)
            raise ex

        return items

    def get_delivery_detail(self, id):
        sql = '''
         select
            dp.id
            , dp."Code"
            , dp."Name" as "Name"
            , dp."Address" as "Address"
            , dp."BusinessNumber" as "BusinessNumber"
            , dp."TelNumber" as "TelNumber"
            , dp."FaxNumber" as "FaxNumber"
            , dp."Homepage" as "Homepage"
            , dp."Description" as "Description"
            , dp."Charger"
            , dp."PhoneNumber"
        from delivery_place dp
        where 1=1
         and dp.id = %(id)s
        '''

        delivery_place = {}
        try:
            dc = {}
            dc['id'] = id
            delivery_place = DbUtil.get_row(sql, dc)

        except Exception as ex:
            LogWriter.add_dblog('error','DefinitionService.get_delivery_detail', ex)
            raise ex

        return delivery_place