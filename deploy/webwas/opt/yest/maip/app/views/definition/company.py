from domain.models.basic import Company
from domain.models.system import ClassData

from domain.services.common import CommonUtil

from domain.services.definition.company import CompanyService
from domain.services.logging import LogWriter


import datetime

def company(context):
    items = []
    gparam = context.gparam
    posparam = context.posparam
    action = gparam.get('action')

    company_service = CompanyService()
    try:
        if action == 'read':
            comp_type= gparam.get('comp_type', '')
            group_name = gparam.get('group_name', '')
            keyword = gparam.get('keyword', '')
            items = company_service.get_company_list(comp_type, group_name, keyword)


        elif action == 'detail':
            id = gparam.get('id', None)
            row = company_service.get_company_detail(id)
            company_types = company_service.get_company_type(id)
            row['company_type'] = company_types
            items = row

        elif action == 'detail2':
            id = gparam.get('id', None)
            items = company_service.get_company_detail2(id)
        elif action == 'checkDate':
            id = gparam.get('id', '')
            material_id = gparam.get('material_id', '')
            company_id = gparam.get('company_id', '')
            apply_start_date = gparam.get('apply_start_date', '')
            apply_end_date = gparam.get('apply_end_date', '')
            items = company_service.check_apply_date(id, material_id, company_id, apply_start_date, apply_end_date)

        elif action == "save":
            id = posparam.get('id', '')
            company = None
            try:
                comp_types = posparam.get('company_type')
                if id:
                    company = Company.objects.get(id=id)
                    #company.Name = posparam.get('name')
                    #company.EngName = posparam.get('eng_name')
                    #company.CompanyType = posparam.get('company_type')
                    #company.BusinessNumber = posparam.get('business_number')
                    #company.CEOName = posparam.get('ceo_name')
                    #company.ZipCode = posparam.get('zip_code')
                    #company.Address = posparam.get('address')
                    #company.TelNumber = posparam.get('tel_number')
                    #company.FaxNumber = posparam.get('fax_number')
                    #company.BusinessType = posparam.get('business_type')
                    #company.BusinessItem = posparam.get('business_item')
                    #company.Email = posparam.get('email')
                    #company.PurchaseSalesDeadline = posparam.get('purchase_sales_deadline')
                    #company.LastTradingDay = posparam.get('last_trading_day')
                    #company.OurManager = posparam.get('our_manager')
                    #company.SalesManager = posparam.get('sales_manager')
                    #company.SalesManagerPhone = posparam.get('sales_manager_phone')
                    #company.AccountManager = posparam.get('account_manager')
                    #company.AccountManagerPhone = posparam.get('account_manager_phone')
                    #company.CreditSalesLimitAmount = posparam.get('credit_sales_limit_amount')
                    #company.TrandingBank = posparam.get('tranding_bank')
                    #company.AccountHolder = posparam.get('account_holder')
                    #company.AccountNumber = posparam.get('account_number')
                    #company.CreditLimitAmount = posparam.get('credit_limit_amount')
                    #company.PaymentCondition = posparam.get('payment_condition')
                else:
                    company = Company()
                company.Name = posparam.get('name')
                company.EngName = posparam.get('eng_name')
                company.Code = CommonUtil.blank_to_none(posparam.get('comp_code'))
                company.Code2 = CommonUtil.blank_to_none(posparam.get('comp_code2'))
                #company.CompanyType = posparam.get('company_type')
                company.BusinessNumber = CommonUtil.blank_to_none(posparam.get('business_number'))
                company.CEOName = posparam.get('ceo_name')
                company.ZipCode = posparam.get('zip_code')
                company.Address = posparam.get('address')
                company.TelNumber = posparam.get('tel_number')
                company.FaxNumber = posparam.get('fax_number')
                company.BusinessType = posparam.get('business_type')
                company.BusinessItem = posparam.get('business_item')
                company.Email = posparam.get('email')
                company.PurchaseSalesDeadline = posparam.get('purchase_sales_deadline')
                
                company.FirstTradingDay = CommonUtil.try_yyyymmdd( posparam.get('first_trading_day'))
                company.LastTradingDay = CommonUtil.try_yyyymmdd( posparam.get('last_trading_day'))
                
                company.OurManager = posparam.get('our_manager')
                company.SalesManager = posparam.get('sales_manager')
                company.SalesManagerPhone = posparam.get('sales_manager_phone')
                company.AccountManager = posparam.get('account_manager')
                company.AccountManagerPhone = posparam.get('account_manager_phone')
                #company.CreditSalesLimitAmount = posparam.get('credit_sales_limit_amount')
                company.TrandingBank = posparam.get('tranding_bank')
                company.AccountHolder = posparam.get('account_holder')
                company.AccountNumber = posparam.get('account_number')
                company.CreditLimitAmount = CommonUtil.try_int(posparam.get('credit_limit_amount'))
                company.PaymentCondition = posparam.get('payment_condition')
                company.Description = posparam.get('description')
                company.Homepage = posparam.get('homepage')

                company.ReceivableAmount = CommonUtil.try_int(posparam.get('receivable_amount'))
                company.UnpaidAmount = CommonUtil.try_int(posparam.get('unpaid_amount'))
                company.ManageRemark = posparam.get('manage_remark')
                company.GroupName = posparam.get('group_name')

                company.MainProduct_id = posparam.get('main_prod')
                company.PaymentMethod = posparam.get('pay_method')
                company.MainProduct_id = posparam.get('main_prod')
         
                company.save()
                comp_id = company.id

                q = ClassData.objects.filter(TableName='company')
                q = q.filter(ClassName='company_type')
                q = q.filter(DataPk=comp_id)
                q = q.delete()

                comp_type_ls = comp_types.split(';')
                for comp_type in comp_type_ls:
                    cd = ClassData()
                    cd.TableName = 'company'
                    cd.ClassName = 'company_type'
                    cd.DataPk = comp_id 
                    cd.Tag = comp_type 
                    cd.save()
                

                items = { 'success' : True, 'success': True, 'id': comp_id }

            except Exception as ex:
                source = '/api/definition/company, action:{}', format(action)
                LogWriter.add_dblog('error', source, ex)
                raise ex

        elif action == 'delete':
            #
            #저장된 단가 삭제 부분 추가 필요
            #
            id = posparam.get('id')
            if id:
                company = Company.objects.get(id = id)
                company.delete()
                items = {'success' : True}

    except Exception as ex:
        source = 'company : action-{}'.format(action)
        LogWriter.add_dblog('error', source , ex)
        #raise ex
        if action == 'delete': #delete2
            err_msg = LogWriter.delete_err_message(ex)
            items = {'success':False, 'message': err_msg}
            return items
        else:
            items = {}
            items['success'] = False
            if not items.get('message'):
                items['message'] = str(ex)
            return items
    return items
